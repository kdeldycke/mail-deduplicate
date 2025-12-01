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

from __future__ import annotations

import email
import hashlib
import logging
import os
import re
from enum import Enum
from functools import cached_property
from mailbox import Message

import arrow
from click_extra import get_current_context

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Iterator
    from mailbox import Mailbox, _ProxyFile

    from .cli import Config


class TooFewHeaders(Exception):
    """Not enough headers were found to produce a solid hash."""


class TimeSource(Enum):
    """Enumeration of all supported mail timestamp sources."""

    DATE_HEADER = "date-header"
    """Timestamp sourced from the message's ``Date`` header."""

    CTIME = "ctime"
    """Timestamp is from the email's file on the filesystem.

    .. attention::
        Only available for ``maildir`` sources.
    """

    def __str__(self) -> str:
        return self.value


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

.. hint::
    Headers from which quotes should be discarded. E.g.:

    .. code-block:: text

        "Bob" <bob@example.com>

    should hash to the same thing as:

    .. code-block:: text

        Bob <bob@example.com>

.. attention::
    These IDs should be kept lower-case, because they are compared to the one provided
    to those provided to the ``-h``/``--hash-header`` option, that is carried by the
    ``hash_headers`` property of the configuration.
"""


class DedupMailMixin(Message):
    """Message with deduplication-specific properties and utilities.

    Extends `standard library's mailbox.Message
    <https://github.com/python/cpython/blob/061965c/Lib/mailbox.py#L1564-L1598>`_,
    and shouldn't be used directly, but composed with ``mailbox.Message`` sub-classes.
    """

    def __init__(self, message: _ProxyFile | None = None) -> None:
        super().__init__(message)

        self.source_path: str | None = None
        """Normalized path to the mailbox this message originates from."""

        self.mail_id: str | None = None
        """Mail ID used to uniquely refers to it in the context of its source."""

        self.path: str
        """Real filesystem location of the mail.

        Returns the individual mail's file for folder-based box types (``maildir`` &
        co.), but returns the whole box path for file-based boxes (``mbox`` & co.). Only
        used by regexp-based selection strategies.
        """

        self.conf: Config
        """Global configuration"""

    def add_box_metadata(self, box: Mailbox, mail_id: str) -> None:
        """Post-instantiation utility to attach to mail some metadata derived from its
        parent box.

        Called right after the ``__init__()`` constructor.

        This allows the mail to carry its own information on its origin box and index.
        """
        self.source_path = box._path
        self.mail_id = mail_id

        # Extract file name and close it right away to reclaim memory.
        mail_file: _ProxyFile = box.get_file(mail_id)
        self.path = mail_file._file.name  # type: ignore[attr-defined]
        mail_file.close()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.source_path}:{self.mail_id}>"

    @cached_property
    def uid(self) -> tuple[str | None, str | None]:
        """Unique ID of the mail."""
        return self.source_path, self.mail_id

    @cached_property
    def parsed_date(self) -> float | None:
        """Parse the mail's date header into float timestamp.

        Returns ``None`` if the mail has no valid date header.
        """
        value = self.get("Date")
        parsed = email.utils.parsedate_tz(value)

        if not parsed:
            logging.debug(f"Mail {self} has no valid Date header: {value!r}")
            return None

        return email.utils.mktime_tz(parsed)

    @cached_property
    def timestamp(self) -> float | None:
        """Compute the normalized canonical timestamp of the mail.

        Sourced from the message's ``Date`` header by default. In the case of
        ``maildir``, can be sourced from the email's file from the filesystem.

        .. warning::
            ``ctime`` does not refer to creation time on POSIX systems, but
            rather `the last time the inode data changed
            <https://userprimary.net/posts/2007/11/18/ctime-in-unix-means-last-change-time-not-create-time/>`_.

        .. todo::
            Investigate what `mailbox.MaildirMessage.get_date()
            <https://docs.python.org/3.11/library/mailbox.html#mailbox.MaildirMessage.get_date>`_
            does and if we can use it.
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

        .. todo::
            Allow customization of the way the size is computed, by getting the file
            size instead for example:
            ```python
            size = os.path.getsize(mail_file)
            ```
        """
        return len("".join(self.body_lines))

    @cached_property
    def body_lines(self) -> list[str]:
        """Return a normalized list of lines from message's body."""
        body = []
        if self.preamble is not None:
            body.extend(self.preamble.splitlines())

        for part in self.walk():
            if part.is_multipart():
                continue

            ctype = part.get_content_type()
            cte = part.get_params(header="Content-Transfer-Encoding")
            if (ctype is not None and not ctype.startswith("text")) or (
                cte is not None and cte[0][0].lower() == "8bit"
            ):
                part_body = part.get_payload(decode=False)
            else:
                charset = part.get_content_charset()
                if charset is None or len(charset) == 0:
                    charsets = ["ascii", "utf-8"]
                else:
                    charsets = [charset]

                part_body = part.get_payload(decode=True)
                for enc in charsets:
                    try:
                        part_body = part_body.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                    except LookupError:
                        continue
                else:
                    part_body = part.get_payload(decode=False)

            body.extend(part_body.splitlines())

        if self.epilogue is not None:
            body.extend(self.epilogue.splitlines())
        return body

    def hash_key(self) -> str:
        """Returns the canonical hash of a mail.

        .. caution::
            This method hasn't been made explicitly into a cached property in order to
            reduce the overall memory footprint.
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
        preparation for hashing."""
        return tuple(
            (header_id, "\n".join(self.normalized_header_values(header_id)))
            for header_id in self.conf["hash_headers"]
            if header_id in self
        )

    def pretty_canonical_headers(self) -> str:
        """Renders a table of headers names and values used to produce the mail's hash.

        .. caution::
            This method hasn't been explicitly made into a cached property in order to
            reduce the overall memory footprint.

        Returns a string ready to be printed.
        """
        ctx = get_current_context()
        return (  # type: ignore[no-any-return]
            "\n"
            + ctx.find_root().render_table(  # type: ignore[attr-defined]
                [*list(self.canonical_headers)],
                headers=("Header ID", "Header value"),
            )
        )

    def serialized_headers(self) -> bytes:
        """Serialize the canonical headers into a single string ready to be hashed.

        At this point we should have an absolute minimum of headers.

        .. caution::
            This method hasn't been explicitly made into a cached property in order to
            reduce the overall memory footprint.
        """
        headers_count = len(self.canonical_headers)
        minimal_headers = self.conf["minimal_headers"]
        msg = self.pretty_canonical_headers()
        if headers_count < minimal_headers:
            logging.warning(msg)
            raise TooFewHeaders(
                f"{headers_count} headers found out of {minimal_headers}."
            )
        else:
            logging.debug(msg)

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
            # Normalize to string
            if isinstance(header_value, email.header.Header):
                value = str(header_value)
            elif isinstance(header_value, bytes):
                value = header_value.decode("utf-8", "replace")
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
        """Strip ``Re:``/``Fwd:`` and ``[list-name]`` prefixes from ``Subject``.

        This cleans up prefixes automatically added by mailing list software, since the
        mail could have been ``CC``'d to multiple lists, in which case it will receive a
        different prefix for each.
        """
        patterns = [
            (r"(?i)(re|fwd?): +(.+)", 2),  # Re:/Fwd: prefix
            (r"\[\w[\w_-]*\w?\] +(.+)", 1),  # [list-name] prefix
        ]
        changed = True
        while changed:
            changed = False
            for pattern, group in patterns:
                if match := re.match(pattern, subject, re.DOTALL):
                    subject = match.group(group)
                    changed = True
                    break
        return subject

    def normalize_content_type(self, value: str) -> str:
        """Normalize ``Content-Type`` by stripping parameters.

        Removes everything after the semicolon, keeping only the MIME type.
        E.g., ``text/plain; charset=utf-8`` becomes ``text/plain``.

        Apparently list servers actually munge ``Content-Type`` e.g. by stripping the
        quotes from ``charset="us-ascii"``. Section 5.1 of RFC2045 says that either form
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
        """Normalize ``Date`` to ``YYYY-MM-DD`` format.

        Date timestamps can differ by seconds or hours for various reasons, so let's
        only honour the date for now and normalize them to UTC timezone.
        """
        if self.parsed_date is not None:
            return arrow.get(self.parsed_date).format("YYYY-MM-DD")
        return value

    def normalize_address_header(self, value: str) -> str:
        """Normalize address headers by removing quotes and collapsing whitespace.

        E.g., ``"Bob" <bob@example.com>`` becomes ``Bob <bob@example.com>``.

        Remove quotes in any headers that contain addresses to ensure a quoted name is
        hashed to the same value as an unquoted one.

        .. danger::
            This may not be the cleanest way to normalize email addresses. E.g.
            ``"Robert \"Bob\"`` becomes ``Robert \Bob\``, but this shouldn't matter for
            hashing purposes as we're just trying to get a good heuristic. Refs: #847 and #846.
        """
        value = re.sub(r'["]', "", value)
        return " ".join(value.split())

    def normalize_to(self, value: str) -> str:
        """Normalize To header."""
        value = self.normalize_address_header(value)
        return self.strip_angle_brackets(value)

    def normalize_message_id(self, value: str) -> str:
        """Normalize Message-ID header by stripping angle brackets.

        E.g., ``<unique-id@example.com>`` becomes ``unique-id@example.com``.
        """
        return self.strip_angle_brackets(value)

    def strip_angle_brackets(self, value: str) -> str:
        """Strip angle brackets from a value if it's a single bracketed item.

        Only strips if the value matches ``<something>`` with no commas.

        .. note::
            Sometimes ``email.parser`` strips the ``<>`` brackets from a ``To:`` header which has a
            single address. I have seen this happen for only one mail in a duplicate pair.
            I'm not sure why (presumably the parser uses ``email.utils.unquote`` somewhere in
            its code path which was only triggered by that mail and not its sister mail),
            but to be safe, we should always strip the ``<>`` brackets to avoid this
            difference preventing duplicate detection.
        """
        if re.match(r"^<[^<>,]+>$", value):
            return email.utils.unquote(value)
        return value
