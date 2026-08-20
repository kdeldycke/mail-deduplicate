# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""A mail wrapped with the deduplication-specific properties: canonical hash,
normalized headers, timestamp, size, and the dehydration machinery keeping memory
flat."""

from __future__ import annotations

import copy
import email.utils
import hashlib
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from email.header import Header
from functools import cached_property
from mailbox import Message
from typing import cast

from click_extra import get_current_context, render_table

from . import StrEnum

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from mailbox import Mailbox, _ProxyFile

    from .cli import Config


class TooFewHeaders(Exception):
    """Not enough headers were found to produce a solid hash."""


class TimeSource(StrEnum):
    """Enumeration of all supported mail timestamp sources."""

    DATE_HEADER = "date-header"
    """Timestamp sourced from the message's `Date` header."""

    CTIME = "ctime"
    """Timestamp is from the email's file on the filesystem.

    ```{attention}
    Only meaningful for sources storing one mail per file, like `maildir`
    and `eml`.
    ```
    """


ADDRESS_HEADERS = frozenset((
    "from",
    "to",
    "cc",
    "bcc",
    "reply-to",
    "sender",
    "return-path",
    "resent-from",
    "resent-to",
    "resent-cc",
    "resent-bcc",
    "resent-reply-to",
    "resent-sender",
    "delivered-to",
    "x-original-to",
    "envelope-to",
    "x-envelope-from",
    "x-envelope-to",
    "disposition-notification-to",
    "original-recipient",
))
"""Headers that contain email addresses.

```{hint}
Headers from which quotes should be discarded, so `"Bob" <bob@example.com>` hashes
to the same thing as `Bob <bob@example.com>`.
```

```{attention}
These IDs should be kept lower-case, because they are compared to the IDs provided
to the `-h`/`--hash-header` option, carried by the `hash_headers` entry of the
configuration.
```
"""


class DedupMailMixin(Message):
    """Message with deduplication-specific properties and utilities.

    Extends [standard library's mailbox.Message](https://github.com/python/cpython/blob/061965c/Lib/mailbox.py#L1564-L1598),
    and shouldn't be used directly, but composed with `mailbox.Message` sub-classes.
    """

    CONTENT_CACHES: tuple[str, ...] = (
        "body_lines",
        "canonical_headers",
        "hash_raw_body",
        "hash_normalized_body",
    )
    """Memoized properties derived from the message content.

    They are only needed while computing hashes, and are dropped by `dehydrate()`
    alongside the parsed message itself.
    """

    resolve_path: Callable[[Mailbox, str], str]
    """Derives the real filesystem location of a mail from its box.

    Set per box format by `make_dedup_mail()`, as folder-based boxes give each mail
    its own file while file-based ones pack them all into the box's single file.
    """

    defects: list = ()  # type: ignore[assignment]
    """Fallback for the parsing defects dropped by `dehydrate()`.

    An empty tuple rather than a list, so it can be shared by every dehydrated mail
    instead of costing one throw-away empty list each: reads still work, and the
    appends only the parser performs fail loudly on a mail that has no message.
    """

    PARSED_MESSAGE_ATTRS: tuple[str, ...] = (
        "_headers",
        "_payload",
        "_unixfrom",
        "preamble",
        "epilogue",
        "defects",
    )
    """Attributes carrying the parsed message, as populated by `email.parser`.

    They hold the bulk of a mail's memory footprint, and are the ones dropped by
    `dehydrate()` and restored by `hydrate()`.
    """

    def __init__(self, message: _ProxyFile | None = None) -> None:
        super().__init__(message)

        self.box: Mailbox | None = None
        """The box this message was read from, kept to re-fetch its content on
        demand after dehydration."""

        self.source_path: str | None = None
        """Normalized path to the mailbox this message originates from."""

        self.mail_id: str | None = None
        """Mail ID used to uniquely refers to it in the context of its source."""

        self.conf: Config
        """Global configuration"""

    _path_override: str | None = None
    """Location of a mail read straight from its file, outside of any box.

    A class attribute, so it costs nothing on the mails that do not need it. Only the
    parallel hashing workers set it: they open a mail by path, and so have no box to
    derive that path back from.
    """

    @property
    def path(self) -> str:
        """Real filesystem location of the mail.

        Returns the individual mail's file for folder-based box types (`maildir` &
        co.), but returns the whole box path for file-based boxes (`mbox` & co.).
        Used by regexp-based selection strategies and to render the mail's repr.

        Derived on access from the box rather than stored, so a retained mail does
        not carry a copy of its own absolute path for the whole run. Raises
        `AttributeError` before the box metadata is attached, so `getattr(mail,
        "path", None)` still reads as absent.
        """
        if self._path_override is not None:
            return self._path_override
        if self.box is None or self.mail_id is None:
            raise AttributeError("No box metadata attached to this mail yet.")
        return self.resolve_path(self.box, self.mail_id)

    def add_box_metadata(self, box: Mailbox, mail_id: str) -> None:
        """Post-instantiation utility to attach to mail some metadata derived from its
        parent box.

        Called right after the `__init__()` constructor.

        This allows the mail to carry its own information on its origin box and index.
        """
        self.box = box
        self.source_path = box._path
        self.mail_id = mail_id

    def __deepcopy__(self, memo: dict) -> DedupMailMixin:
        """Deep-copy the mail while sharing its box and configuration references.

        `email.generator` deep-copies a message to flatten 8-bit payloads without
        mutating the original, which `str(mail)` triggers. The parent box can
        carry open file handles that cannot be copied, and both the box and the
        configuration are shared references by design, so they are passed through
        as-is.
        """
        clone = copy.copy(self)
        memo[id(self)] = clone
        for name, value in vars(self).items():
            if name not in ("box", "conf"):
                setattr(clone, name, copy.deepcopy(value, memo))
        return clone

    @property
    def is_hydrated(self) -> bool:
        """Whether the mail still carries its parsed message."""
        return hasattr(self, "_payload")

    def dehydrate(self) -> None:
        """Reduce the mail to the lightweight metadata needed by the next steps.

        Memoizes the scalar properties consumed by selection strategies (timestamp,
        and size when the decoded body is at hand), then drops the parsed message and
        every cached copy of its content. This cuts the resident footprint of a
        retained mail from the full size of its message to a few hundred bytes,
        whatever the number of mails processed. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/761

        No-op if the mail is already dehydrated. The dropped content is re-read from
        the source box by `hydrate()` when a later step needs it again.
        """
        if not self.is_hydrated:
            return

        # Memoize the cheap scalars while the parsed message is still available.
        _ = self.timestamp
        if "body_lines" in self.__dict__:
            _ = self.size

        for name in self.CONTENT_CACHES:
            self.__dict__.pop(name, None)

        # Drop the parsed message. The two core attributes are deleted rather than
        # emptied, so any unforeseen direct access fails loudly instead of silently
        # misreading the mail as empty.
        del self._headers  # type: ignore[attr-defined]
        del self._payload  # type: ignore[attr-defined]
        self._unixfrom = None
        self.preamble = None
        self.epilogue = None
        # Fall back to the shared empty tuple on the class instead of holding a
        # per-mail empty list.
        del self.defects

    def hydrate(self) -> None:
        """Restore the full parsed message dropped by `dehydrate()`.

        Re-reads the mail from its source box, through the same parsing path that
        produced it in the first place, so the restored content is identical.
        No-op if the mail still carries its parsed message.
        """
        if self.is_hydrated:
            return

        # Asserts to please the type checker.
        assert self.box is not None
        assert self.mail_id is not None

        fresh = self.box[self.mail_id]
        for name in self.PARSED_MESSAGE_ATTRS:
            setattr(self, name, getattr(fresh, name))

    @contextmanager
    def hydrated(self) -> Iterator[DedupMailMixin]:
        """Borrow the full parsed message for the duration of the block.

        Restores the message on the way in and releases it on the way out, so a step
        needing the whole mail after the hashing one keeps its content resident only
        while it uses it, and memory stays flat across a loop of mails.
        """
        self.hydrate()
        try:
            yield self
        finally:
            self.dehydrate()

    def __repr__(self) -> str:
        """Renders the fully-qualified path of the mail's own file, so it can be
        copy-pasted as-is for direct inspection.

        Mails from file-based boxes share the box's path, so the mail ID is appended
        to tell them apart. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/157
        """
        path = getattr(self, "path", None)
        if path and path != self.source_path:
            return f"<{self.__class__.__name__} {path}>"
        return f"<{self.__class__.__name__} {self.source_path}:{self.mail_id}>"

    @cached_property
    def parsed_date(self) -> float | None:
        """Parse the mail's date header into float timestamp.

        Returns `None` if the mail has no valid date header.

        Self-hydrating: re-reads the message from its box if it was dehydrated.
        """
        self.hydrate()
        value = self.get("Date")
        parsed = email.utils.parsedate_tz(value)

        if not parsed:
            logging.debug(f"Mail {self!r} has no valid Date header: {value!r}")
            return None

        return float(email.utils.mktime_tz(parsed))

    @cached_property
    def timestamp(self) -> float | None:
        """Compute the normalized canonical timestamp of the mail.

        Sourced from the message's `Date` header by default. In the case of
        `maildir`, can be sourced from the email's file from the filesystem.

        ```{warning}
        `ctime` does not refer to creation time on POSIX systems, but
        rather [the time of the last metadata change](https://docs.python.org/3/library/os.path.html#os.path.getctime).
        ```

        ```{todo}
        Investigate what [mailbox.MaildirMessage.get_date()](https://docs.python.org/3.11/library/mailbox.html#mailbox.MaildirMessage.get_date)
        does and if we can use it.
        ```
        """
        if self.conf["time_source"] == TimeSource.CTIME:
            return os.path.getctime(self.path)

        return self.parsed_date

    @cached_property
    def size(self) -> int:
        """Returns canonical mail size.

        Size is computed as the length of the message body, i.e. the payload of the mail
        stripped of all its headers, not from the mail file persisting on the file-
        system.

        ```{todo}
        Allow customization of the way the size is computed, by getting the file
        size instead, for example with `os.path.getsize(mail_file)`.
        ```
        """
        return len("".join(self.body_lines))

    @cached_property
    def body_lines(self) -> list[str]:
        """Return a normalized list of lines from message's body.

        Self-hydrating: re-reads the message from its box if it was dehydrated.
        """
        self.hydrate()
        body: list[str] = []
        if self.preamble is not None:
            body.extend(self.preamble.splitlines())

        for part in self.walk():
            if part.is_multipart():
                continue
            body.extend(self.decode_part(part).splitlines())

        if self.epilogue is not None:
            body.extend(self.epilogue.splitlines())
        return body

    def decode_part(self, part: Message) -> str:
        """Decode a single message part to string."""
        ctype = part.get_content_type()
        cte = part.get_params(header="Content-Transfer-Encoding")

        # Binary or 8bit content: return as-is
        if (ctype and not ctype.startswith("text")) or (
            cte and cte[0][0].lower() == "8bit"
        ):
            return cast(str, part.get_payload(decode=False))

        # Try to decode with charset(s)
        charset = part.get_content_charset()
        charsets = [charset] if charset else ["ascii", "utf-8"]

        part_body_bytes = part.get_payload(decode=True)
        if isinstance(part_body_bytes, bytes):
            for enc in charsets:
                try:
                    return part_body_bytes.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue

        return cast(str, part.get_payload(decode=False))

    def hash_key(self) -> str:
        """Returns the canonical hash of a mail.

        ```{caution}
        This method hasn't been made explicitly into a cached property in order to
        reduce the overall memory footprint.
        ```
        """
        serialized_headers = self.serialized_headers()
        logging.debug(f"Serialized headers: {serialized_headers!r}")
        hash_value = hashlib.sha224(serialized_headers).hexdigest()
        logging.debug(f"Hash: {hash_value}")
        return hash_value

    @cached_property
    def hash_raw_body(self) -> str:
        """Returns the canonical body hash of a mail."""
        serialized_raw_body = "\n".join(self.body_lines).encode("utf-8")
        hash_value = hashlib.sha224(serialized_raw_body).hexdigest()
        logging.debug(f"Body raw hash: {hash_value}")
        return hash_value

    @cached_property
    def hash_normalized_body(self) -> str:
        """Returns the normalized body hash of a mail."""
        serialized_normalized_body = "".join(
            [re.sub(r"\s", "", line) for line in self.body_lines],
        ).encode("utf-8")
        hash_value = hashlib.sha224(serialized_normalized_body).hexdigest()
        logging.debug(f"Body normalized hash: {hash_value}")
        return hash_value

    @cached_property
    def canonical_headers(self) -> tuple[tuple[str, str], ...]:
        """Returns the full list of all canonical headers names and values in
        preparation for hashing.

        Self-hydrating: re-reads the message from its box if it was dehydrated.
        """
        self.hydrate()
        return tuple(
            (header_id, "\n".join(self.normalized_header_values(header_id)))
            for header_id in self.conf["hash_headers"]
            if header_id in self
        )

    def pretty_canonical_headers(self) -> str:
        """Renders a table of headers names and values used to produce the mail's hash.

        ```{caution}
        This method hasn't been explicitly made into a cached property in order to
        reduce the overall memory footprint.
        ```

        Returns a string ready to be printed.
        """
        table_data = list(self.canonical_headers)
        headers = ("Header ID", "Header value")
        # get_current_context() is silent here so hashing can run in a --jobs worker
        # process, which does not inherit Click's context. With a context the table
        # honors --table-format; without one it falls back to the default.
        #
        # Header values run long: a References chain or a verbose Subject overflows
        # the terminal several times over. Sizing the value column to what is left
        # keeps the table readable, and leaving the wrapping to the renderer avoids
        # baking line breaks into the cells of the structured formats.
        ctx = get_current_context(silent=True)
        if ctx is not None:
            rendered: str = ctx.find_root().render_table(  # type: ignore[attr-defined]
                table_data,
                headers=headers,
                max_column_widths=(None, "auto"),
            )
        else:
            rendered = render_table(
                table_data, headers=headers, max_column_widths=(None, "auto")
            )
        return "\n" + rendered

    def serialized_headers(self) -> bytes:
        """Serialize the canonical headers into a single string ready to be hashed.

        At this point we should have an absolute minimum of headers.

        ```{caution}
        This method hasn't been explicitly made into a cached property in order to
        reduce the overall memory footprint.
        ```
        """
        headers_count = len(self.canonical_headers)
        minimal_headers = self.conf["minimal_headers"]
        if headers_count < minimal_headers:
            logging.warning(self.pretty_canonical_headers())
            raise TooFewHeaders(
                f"{headers_count} headers found out of {minimal_headers}."
            )
        # Rendering the table costs more than the hash itself, and its result is
        # discarded at any level above debug, so only pay for it when it is logged.
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(self.pretty_canonical_headers())

        return "\n".join(
            [f"{h_id}: {h_value}" for h_id, h_value in self.canonical_headers],
        ).encode("utf-8")

    def normalized_header_values(self, header_id: str) -> Iterator[str]:
        """Returns all normalized values of a header.

        Values are cleaned-up into their canonical form.
        """
        all_values = self.get_all(header_id)
        if all_values is None:
            return

        for header_value in all_values:
            if isinstance(header_value, Header):  # type: ignore[unreachable]
                value = str(header_value)  # type: ignore[unreachable]
            elif isinstance(header_value, bytes):  # type: ignore[unreachable]
                value = header_value.decode(  # type: ignore[unreachable]
                    "utf-8", "replace"
                )
            else:
                value = header_value

            # Normalize whitespace
            value = " ".join(value.split())

            # Header-specific normalization: dispatch to normalize_<header_id> methods
            normalizer = getattr(self, f"normalize_{header_id.replace('-', '_')}", None)
            if normalizer:
                value = normalizer(value)
            elif header_id in ADDRESS_HEADERS:
                value = self.normalize_address_header(value)

            # Only return non-empty values
            if value.strip():
                yield value

    def normalize_subject(self, subject: str) -> str:
        """Strip `Re:`/`Fwd:` and `[list-name]` prefixes from `Subject`.

        This cleans up prefixes automatically added by mailing list software, since the
        mail could have been `CC`'d to multiple lists, in which case it will receive a
        different prefix for each.
        """
        return re.sub(r"(?i)^(?:(?:re|fwd?): +|\[\w[\w_-]*\w?\] +)+", "", subject)

    def normalize_content_type(self, value: str) -> str:
        """Normalize `Content-Type` by stripping parameters.

        Removes everything after the semicolon, keeping only the MIME type.
        E.g., `text/plain; charset=utf-8` becomes `text/plain`.

        Apparently list servers actually munge `Content-Type` e.g. by stripping the
        quotes from `charset="us-ascii"`. Section 5.1 of RFC2045 says that either form
        is valid (and they are equivalent).

        Additionally, with multipart/mixed, boundary delimiters can vary by recipient.
        We need to allow for duplicates coming from multiple recipients, since for
        example you could be signed up to the same list twice with different
        addresses. Or maybe someone bounces you a load of mail some of which is from a
        mailing list you're both subscribed to - then it's still useful to be able to
        eliminate duplicates.
        """
        return re.sub(";.*", "", value)

    def normalize_date(self, value: str) -> str:
        """Normalize `Date` to `YYYY-MM-DD` format.

        Date timestamps can differ by seconds or hours for various reasons, so only
        the date is honoured, normalized to the UTC timezone.

        ```{todo}
        Revisit the day-level granularity, and whether the time of the day should
        take part in the hash.
        ```
        """
        if self.parsed_date is not None:
            utc_date = datetime.fromtimestamp(self.parsed_date, tz=timezone.utc).date()
            return utc_date.isoformat()
        return value

    def normalize_address_header(self, value: str) -> str:
        """Normalize address headers by removing quotes and collapsing whitespace.

        E.g., `"Bob" <bob@example.com>` becomes `Bob <bob@example.com>`.

        Remove quotes in any headers that contain addresses to ensure a quoted name is
        hashed to the same value as an unquoted one.

        ```{danger}
        This may not be the cleanest way to normalize email addresses. E.g.
        `"Robert \\"Bob\\""` becomes `Robert \\Bob\\`, but this shouldn't matter for
        hashing purposes as we're just trying to get a good heuristic. Refs:
        [#846](https://github.com/kdeldycke/mail-deduplicate/issues/846) and
        [#847](https://github.com/kdeldycke/mail-deduplicate/pull/847).
        ```
        """
        value = re.sub(r'["]', "", value)
        value = " ".join(value.split())
        return self.strip_angle_brackets(value)

    def normalize_message_id(self, value: str) -> str:
        """Normalize Message-ID header by stripping angle brackets.

        E.g., `<unique-id@example.com>` becomes `unique-id@example.com`.
        """
        return self.strip_angle_brackets(value)

    def strip_angle_brackets(self, value: str) -> str:
        """Strip angle brackets from a value if it's a single bracketed item.

        Only strips if the value matches `<something>` with no commas.

        ```{note}
        Sometimes `email.parser` strips the `<>` brackets from a `To:` header which has a
        single address. I have seen this happen for only one mail in a duplicate pair.
        I'm not sure why (presumably the parser uses `email.utils.unquote` somewhere in
        its code path which was only triggered by that mail and not its sister mail),
        but to be safe, we should always strip the `<>` brackets to avoid this
        difference preventing duplicate detection.
        ```
        """
        if re.match(r"^<[^<>,]+>$", value):
            return str(email.utils.unquote(value))
        return value
