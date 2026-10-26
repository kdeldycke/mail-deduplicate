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
"""Bug reports for the errors mdedup has no rule for.

Such an error is a bug in mdedup, or a mail shape it does not handle yet. To fix it,
a maintainer needs two facts: the code that raised the error, and the shape of the
mail that triggered it. This module collects both, and renders them as a block that
a user can paste into an issue.

```{caution}
A report never holds mail content. Mails carry the personal data of their senders
and recipients, and issues are public. So `fingerprint()` describes a mail by its
structure alone. The traceback keeps module names and line numbers, and drops the
file paths, which hold the name of the user on most systems.
```

```{todo}
Contribute the crash handler, the environment and options lines and the report
invitation to [click-extra](https://github.com/kdeldycke/click-extra), so every
Click Extra CLI can invite bug reports. mdedup then keeps only the mail fingerprint
and the quarantine of the failing mails.
```
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from email import message_from_bytes
from email.message import Message
from typing import cast
from urllib.parse import urlencode

from click.exceptions import Exit
from click_extra import (
    Abort,
    ClickException,
    ParameterSource,
    Path as PathType,
    context,
    get_current_context,
)
from click_extra.version import env_summary
from extra_platforms import is_any_agent

from . import __version__
from .mail_box import BoxFormat

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Sequence
    from mailbox import Mailbox
    from types import TracebackType

    import click

    from .deduplicate import Deduplicate
    from .mail import DedupMailMixin


ISSUES_URL = "https://github.com/kdeldycke/mail-deduplicate/issues"
"""Where users file bug reports.

Repeats the `Issues` URL of `pyproject.toml`, and a test keeps the two in sync: a
binary built by Nuitka ships no package metadata to read it from.
"""

REPORT_FORM = "bug-report.yml"
"""File name of the issue form a report links to, in `.github/ISSUE_TEMPLATE/`."""

REPORT_START = "----- 8< ----- mdedup bug report ----- 8< -----"
"""First line of the block a user pastes into an issue."""

REPORT_END = "----- 8< ----- end of bug report ----- 8< -----"
"""Last line of the block a user pastes into an issue."""

FAILURE_ATTRIBUTE = "mdedup_failure"
"""Attribute of an exception that holds the `Failure` attached by `blame()`."""

FINGERPRINTED_MAILS = 2
"""Mails of one failure that get a fingerprint.

A failing duplicate set does not tell which of its mails caused the error, and its
first two mails usually include the culprit.
"""

MAX_FINGERPRINT_LINES = 60
"""Cap on the lines of a fingerprint, for mails with hundreds of headers or parts."""

MAX_FRAMES = 12
"""Innermost frames kept from a traceback. A `RecursionError` has a thousand."""

MAX_KINDS = 5
"""Kinds of failure detailed in a report. The warnings of the run name the others."""

MAX_VALUE_LENGTH = 200
"""Cap on the characters of an error message or of a header value shown verbatim."""

PARAMETER_HEADERS = frozenset(("content-disposition", "content-type"))
"""Headers a fingerprint shows with their structure only: see `structure()`."""

SAFE_PARAMETERS = frozenset((
    "charset",
    "delsp",
    "format",
    "micalg",
    "protocol",
    "report-type",
    "type",
))
"""Parameters of `PARAMETER_HEADERS` shown as they are: they tell how to read a part.

`structure()` names the `SHAPED_PARAMETERS` without their value, and hides the name
of any other parameter too.
"""

SAMPLES = 3
"""Failures of each kind that a report details, with the fingerprint of their mails.

More samples of the same bug add length to a report, not information, and each
fingerprint costs one more read and parse of its mail.
"""

SHAPED_PARAMETERS = frozenset(("boundary", "filename", "name"))
"""Parameters of `PARAMETER_HEADERS` a fingerprint names, with their shape alone.

They can hold content: a file name, or a boundary built from a sender address.
"""

VERBATIM_HEADERS = frozenset(("content-transfer-encoding", "date", "mime-version"))
"""Headers a fingerprint shows as they are: they hold structure, not content.

`Date` holds a time and no name, and its parsing caused several of the past crashes.
See: https://github.com/kdeldycke/mail-deduplicate/issues/954 and
https://github.com/kdeldycke/mail-deduplicate/issues/600
"""

CONTROL_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
"""C0 control bytes and `DEL`, except the tab and the line breaks of a mail."""

ENCODED_WORD = re.compile(r"=\?([^?\s]+)\?([bBqQ])\?")
"""Start of an RFC 2047 encoded word: its charset and its encoding."""

TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+(?:/[!#$%&'*+.^_`|~0-9A-Za-z-]+)?")
"""An RFC 2045 token, or a `type/subtype` pair of them."""


def plural(count: int, singular: str, several: str | None = None) -> str:
    """Count things in words, or say nothing about a count of zero."""
    if not count:
        return ""
    return f"{count} {singular if count == 1 else several or f'{singular}s'}"


def to_bytes(text: str) -> bytes:
    """Recover the bytes a parsed value came from.

    Parsing a mail from bytes keeps each non-ASCII byte as a lone surrogate, which
    `surrogateescape` turns back into that byte. Other surrogates come from no byte,
    so `surrogatepass` writes them as the invalid UTF-8 they are.
    """
    try:
        return text.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return text.encode("utf-8", "surrogatepass")


def byte_class(value: str | bytes | None) -> str:
    """Describe a value by its length and the kind of its bytes, never by its bytes."""
    if value is None:
        return "none"
    raw = value if isinstance(value, bytes) else to_bytes(value)
    if not raw:
        return "empty"
    if raw.isascii():
        kind = "ascii"
    else:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            kind = "8-bit, not UTF-8"
        else:
            kind = "8-bit UTF-8"
    if CONTROL_BYTES.search(raw):
        kind += ", control bytes"
    return f"{len(raw)} B {kind}"


def shape(value: str) -> str:
    """Describe a value by its bytes, its folding and its encoded words."""
    details = [byte_class(value)]
    line_count = value.count("\n") + 1
    if line_count > 1:
        details.append(f"{line_count} lines")
    encodings = sorted({
        f"{charset.lower()}/{encoding.upper()}"
        for charset, encoding in ENCODED_WORD.findall(value)
    })
    if encodings:
        details.append(f"encoded words {', '.join(encodings)}")
    return f"<{', '.join(details)}>"


def verbatim(value: str) -> str:
    """Show a value as it is, with its folding collapsed and its length capped.

    A value holding non-ASCII bytes renders as `bytes`, so each byte shows as an
    escape rather than as a lone surrogate.
    """
    flat = " ".join(value.split())
    if len(flat) > MAX_VALUE_LENGTH:
        flat = f"{flat[:MAX_VALUE_LENGTH]}..."
    return repr(flat) if flat.isascii() else repr(to_bytes(flat))


def split_parameters(value: str) -> list[str]:
    """Split a header value on its semicolons, except the ones in a quoted string."""
    parts = []
    current: list[str] = []
    quoted = escaped = False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [" ".join(part.split()) for part in parts]


def structure(value: str) -> str:
    """Show a `Content-Type` or `Content-Disposition` value by its structure alone.

    The leading `type/subtype` or disposition shows as it is, and so do the
    `SAFE_PARAMETERS`. The `SHAPED_PARAMETERS` keep their name, and any other
    parameter shows as `?`, all of them with the shape of their value only.
    """
    main, *parameters = split_parameters(value)
    shown = [main if TOKEN.fullmatch(main) else shape(main)]
    for parameter in parameters:
        if not parameter:
            continue
        name, equal, argument = parameter.partition("=")
        name = name.strip().lower()
        argument = argument.strip()
        if equal and name in SAFE_PARAMETERS and TOKEN.fullmatch(argument.strip('"')):
            shown.append(f"{name}={argument}")
        elif equal and name.split("*")[0] in SHAPED_PARAMETERS:
            shown.append(f"{name}: {shape(argument)}")
        else:
            shown.append(f"?: {shape(parameter)}")
    return "; ".join(shown)


def header_value(name: str, value: str) -> str:
    """Show a header value as its name allows: verbatim, by structure, or by shape."""
    lower = name.lower()
    if lower in VERBATIM_HEADERS:
        return verbatim(value)
    if lower in PARAMETER_HEADERS:
        return structure(value)
    return shape(value)


def line_endings(raw: bytes) -> str:
    """Name the line endings of a mail, with their counts when they are mixed."""
    crlf = raw.count(b"\r\n")
    counts = {
        "CRLF": crlf,
        "LF": raw.count(b"\n") - crlf,
        "CR": raw.count(b"\r") - crlf,
    }
    found = {kind: count for kind, count in counts.items() if count}
    if not found:
        return "none"
    if len(found) == 1:
        return next(iter(found))
    return "mixed: " + ", ".join(f"{count} {kind}" for kind, count in found.items())


def first_raw(part: Message, name: str) -> str | None:
    """The raw value of the first header of a part with that name.

    A parsed header holding 8-bit bytes reads back as a `Header` object, and its raw
    value as a string with lone surrogates, which `to_bytes()` turns back to bytes.
    """
    for key, value in part.raw_items():
        if key.lower() == name:
            return str(value)
    return None


def part_lines(part: Message, depth: int = 0) -> Iterator[str]:
    """One line per MIME part, with the subparts of a multipart indented under it."""
    line = "  " * depth + part.get_content_type()
    charset = part.get_content_charset()
    if charset:
        line += f"; charset={charset}" if TOKEN.fullmatch(charset) else "; charset=?"
    encoding = first_raw(part, "content-transfer-encoding")
    if encoding is not None:
        encoding = encoding.strip().lower()
        line += f", cte {encoding if TOKEN.fullmatch(encoding) else shape(encoding)}"
    disposition = part.get_content_disposition()
    if disposition:
        line += f", {disposition if TOKEN.fullmatch(disposition) else '?'}"

    if part.is_multipart():
        line += (
            f", preamble {byte_class(part.preamble)}, "
            f"epilogue {byte_class(part.epilogue)}"
        )
    else:
        # Without a transfer encoding to undo, decoding returns the raw bytes. A raw
        # read instead would decode 8-bit bytes with the charset, and hide them.
        decoded = part.get_payload(decode=True)
        if not isinstance(decoded, bytes):
            decoded = None
        if encoding in ("base64", "quoted-printable"):
            raw_payload = part.get_payload(decode=False)
            if not isinstance(raw_payload, str):
                raw_payload = None
            line += f", payload {byte_class(raw_payload)}"
            line += f", decoded {byte_class(decoded)}"
        else:
            line += f", payload {byte_class(decoded)}"
        maintype = part.get_content_maintype()
        if decoded and charset and TOKEN.fullmatch(charset) and maintype == "text":
            try:
                decoded.decode(charset)
            except UnicodeDecodeError:
                line += ", invalid for its charset"
            except (LookupError, ValueError):
                line += ", unknown charset"

    if part.defects:
        defects = sorted({type(defect).__name__ for defect in part.defects})
        line += f", defects {', '.join(defects)}"
    yield line

    if part.is_multipart():
        for subpart in part.get_payload():
            if isinstance(subpart, Message):
                yield from part_lines(subpart, depth + 1)


def fingerprint(raw: bytes) -> str:
    """Describe a mail by its structure, with none of its content.

    The description shows the size and line endings of the mail, then every header
    name, in order. Headers in `VERBATIM_HEADERS` show their value, those in
    `PARAMETER_HEADERS` their structure, and any other one only the shape of its
    value: length, kind of bytes, folding and encoded words. Then comes the MIME
    tree, with the type, charset, transfer encoding and kind of bytes of each part,
    the preamble and epilogue of each multipart, and the defects the parser found.

    Never raises: a mail too broken to describe gets a line saying so.
    """
    try:
        message = message_from_bytes(raw)
        headers = list(message.raw_items())
        lines = [
            f"size: {len(raw)} B, line endings: {line_endings(raw)}",
            f"headers: {len(headers)}",
            *(f"  {name}: {header_value(name, str(value))}" for name, value in headers),
            "structure:",
            *(f"  {line}" for line in part_lines(message)),
        ]
    except Exception as expt:  # noqa: BLE001
        logging.debug(f"Cannot fingerprint a mail: {expt!r}")
        return f"Fingerprint unavailable: {type(expt).__name__}."
    if len(lines) > MAX_FINGERPRINT_LINES:
        extra = len(lines) - MAX_FINGERPRINT_LINES
        lines = [*lines[:MAX_FINGERPRINT_LINES], f"... {extra} more lines"]
    return "\n".join(lines)


def mail_bytes(mail: DedupMailMixin) -> bytes:
    """Read the raw bytes of a mail again, from its own file or from its box."""
    if mail._path_override is not None:
        with open(mail._path_override, "rb") as file:
            return file.read()
    if mail.box is None or mail.mail_id is None:
        raise LookupError("The mail has no box to be read from.")
    return mail.box.get_bytes(mail.mail_id)


def fingerprint_mail(mail: DedupMailMixin) -> str:
    """The `fingerprint()` of a mail, read again from its source.

    Never raises: a mail that cannot be read again gets a line saying so.
    """
    try:
        raw = mail_bytes(mail)
    except Exception as expt:  # noqa: BLE001
        return f"Fingerprint unavailable: cannot read the mail ({type(expt).__name__})."
    return fingerprint(raw)


def box_format_of(item: DedupMailMixin | Mailbox) -> str:
    """The format of a box, or of the box a mail comes from."""
    for box_format in BoxFormat:
        if isinstance(item, (box_format.message_class, box_format.base_class)):
            return str(box_format)
    return type(item).__name__


def describe(expt: BaseException) -> str:
    """The class and message of an exception, on one line of capped length."""
    name = type(expt).__qualname__
    module = type(expt).__module__
    if module != "builtins":
        name = f"{module}.{name}"
    message = " ".join(str(expt).split())
    if len(message) > MAX_VALUE_LENGTH:
        message = f"{message[:MAX_VALUE_LENGTH]}..."
    return f"{name}: {message}" if message else name


def compact_frames(tb: TracebackType | None) -> tuple[str, ...]:
    """A traceback as `module:line in function` entries, outermost first.

    Module names say as much as file paths about the code, and nothing about where
    it is installed, so they are what the report shows. A method shows with its
    class, like `Maildir.add`, from Python 3.11 on.
    """
    frames = [
        f"{frame.f_globals.get('__name__', '?')}:{lineno} in "
        f"{getattr(frame.f_code, 'co_qualname', frame.f_code.co_name)}"
        for frame, lineno in traceback.walk_tb(tb)
    ]
    if len(frames) > MAX_FRAMES:
        outer = len(frames) - MAX_FRAMES
        frames = [f"... {outer} outer frames", *frames[-MAX_FRAMES:]]
    return tuple(frames)


@dataclass(frozen=True)
class Failure:
    """An error mdedup has no rule for, reduced to strings.

    Strings can leave a worker process, and keep nothing alive: the mails, boxes and
    frames of the error are dropped as soon as it is captured.
    """

    step: str
    """What the run was doing: `hashing`, `selecting`, `deleting`, and so on."""

    error: str
    """The class and message of the exception."""

    frames: tuple[str, ...]
    """The traceback, as `compact_frames()` renders it."""

    culprits: tuple[str, ...] = ()
    """The `repr()` of each mail involved. They hold paths, so they never reach the
    report block."""

    formats: tuple[str, ...] = ()
    """The box format of each mail involved."""

    fingerprints: tuple[str, ...] = ()
    """The fingerprint of the first mails involved, or nothing for a failure that is
    not a sample."""

    trace: str = ""
    """The full traceback, for the debug log, or nothing for a failure that is not a
    sample."""

    @property
    def kind(self) -> tuple[str, str, str]:
        """Failures of one kind share their step, exception class and raising line."""
        return (
            self.step,
            self.error.partition(":")[0],
            self.frames[-1] if self.frames else "",
        )

    @property
    def title(self) -> str:
        """The title of an issue reporting the failure: its exception class and step.

        Reports of the same bug get the same title, so GitHub lists the issue already
        open for it while the next user types theirs.
        """
        return f"{self.kind[1]} while {self.step}"


def capture(
    expt: BaseException,
    step: str,
    mails: Sequence[DedupMailMixin] = (),
    sample: bool = True,
) -> Failure:
    """Reduce an error to a `Failure`.

    Only a sample gets the fingerprints of its first mails and the full traceback:
    both cost far more than the rest.
    """
    tb = expt.__traceback__
    # `blame()` and `report_unexpected_errors()` catch the error once it was thrown
    # back into their own frame, which then heads its traceback.
    if tb is not None and tb.tb_frame.f_globals.get("__name__") == __name__:
        tb = tb.tb_next
    failure = Failure(
        step=step,
        error=describe(expt),
        frames=compact_frames(tb),
        culprits=tuple(repr(mail) for mail in mails),
        formats=tuple(box_format_of(mail) for mail in mails),
    )
    if not sample:
        return failure
    return replace(
        failure,
        fingerprints=tuple(
            fingerprint_mail(mail) for mail in mails[:FINGERPRINTED_MAILS]
        ),
        trace="".join(traceback.format_exception(type(expt), expt, tb)),
    )


def failure_lines(samples: Sequence[Failure], title: str) -> Iterator[str]:
    """The lines of a report detailing one kind of failure."""
    formats = sorted({
        box_format for sample in samples for box_format in sample.formats
    })
    first = samples[0]
    yield ""
    yield f"{title} ({', '.join(formats)})" if formats else title
    yield first.error
    yield from (f"  {frame}" for frame in first.frames)
    for sample in samples:
        for mail_fingerprint in sample.fingerprints:
            yield "Fingerprint of a mail involved:"
            yield from (f"  {line}" for line in mail_fingerprint.splitlines())


class FailureLog:
    """The failures of a run: each one counted, the first `SAMPLES` of a kind kept.

    Memory stays flat however many mails fail the same way, which a single bug can
    make all of them do.
    """

    def __init__(self) -> None:
        self.counts: Counter[tuple[str, str, str]] = Counter()
        """Number of failures of each kind."""

        self.samples: dict[tuple[str, str, str], list[Failure]] = {}
        """The first failures of each kind, in the order they happened."""

    def __bool__(self) -> bool:
        return bool(self.counts)

    def capture(
        self, expt: BaseException, step: str, mails: Sequence[DedupMailMixin] = ()
    ) -> Failure:
        """Reduce an error to a `Failure`, sampled while its kind has room left."""
        failure = capture(expt, step, mails, sample=False)
        if len(self.samples.get(failure.kind, ())) < SAMPLES:
            failure = capture(expt, step, mails)
        return failure

    def add(self, failure: Failure) -> None:
        """Count a failure, and keep it if its kind still has room for a sample."""
        self.counts[failure.kind] += 1
        kept = self.samples.setdefault(failure.kind, [])
        if len(kept) < SAMPLES:
            kept.append(failure)

    def headline(self) -> str:
        """The first line of the report, saying how much the failures set aside."""
        mails = sum(n for kind, n in self.counts.items() if kind[0] == "hashing")
        sets = sum(n for kind, n in self.counts.items() if kind[0] != "hashing")
        aside = " and ".join(
            part
            for part in (
                plural(mails, "mail"),
                plural(sets, "set of duplicates", "sets of duplicates"),
            )
            if part
        )
        return (
            f"mdedup set aside {aside} after unexpected errors, and acted on none of "
            "their mails."
        )

    def title(self) -> str:
        """The title of the issue reporting the failures: that of their most frequent
        kind."""
        kind = max(self.counts, key=self.counts.__getitem__)
        return self.samples[kind][0].title

    def traces(self) -> Iterator[str]:
        """The full traceback of each sample, for the debug log."""
        for samples in self.samples.values():
            for sample in samples:
                if sample.trace:
                    yield sample.trace

    def report_lines(self) -> Iterator[str]:
        """The lines of the report detailing each kind of failure, most frequent
        first."""
        kinds = sorted(self.counts, key=self.counts.__getitem__, reverse=True)
        for index, kind in enumerate(kinds[:MAX_KINDS], 1):
            count = self.counts[kind]
            if kind[0] == "hashing":
                unit = plural(count, "mail")
            else:
                unit = plural(count, "set of duplicates", "sets of duplicates")
            title = f"Failure {index} of {len(kinds)}, while {kind[0]}: {unit}"
            yield from failure_lines(self.samples[kind], title)
        if len(kinds) > MAX_KINDS:
            yield ""
            yield (
                f"{len(kinds) - MAX_KINDS} more kinds of failure: the warnings of the "
                "run name their mails."
            )


def option_words(param: click.Parameter, value: object) -> list[str]:
    """Render one parameter as typed on the command line, with its values masked.

    A path or a regular expression can name the folders and correspondents of the
    user, so each shows as a placeholder.
    """
    if param.param_type_name == "argument":
        count = len(value) if isinstance(value, tuple) else 1
        return ["<path>"] * count
    flag = max(param.opts, key=len)
    if getattr(param, "is_flag", False):
        if value:
            return [flag]
        secondary = getattr(param, "secondary_opts", ())
        return [max(secondary, key=len)] if secondary else []
    items = cast("tuple", value) if getattr(param, "multiple", False) else (value,)
    words: list[str] = []
    for item in items:
        if isinstance(param.type, PathType) or isinstance(item, os.PathLike):
            shown = "<path>"
        elif isinstance(item, re.Pattern):
            shown = "<regexp>"
        else:
            shown = str(item)
        words.extend((flag, shown))
    return words


def options_summary() -> str:
    """The parameters of the run that do not come from their default, masked.

    The parameters of Click Extra keep no value of their own in the context, and
    none of them changes what mdedup does to a mail, except `--jobs`.
    """
    ctx = get_current_context(silent=True)
    if ctx is None:
        return "unknown"
    words: list[str] = []
    for param in ctx.command.get_params(ctx):
        if param.name is None or ctx.get_parameter_source(param.name) in (
            None,
            ParameterSource.DEFAULT,
        ):
            continue
        if param.name == "jobs":
            words.extend(("--jobs", str(context.get(ctx, context.JOBS, 1))))
        elif param.name in ctx.params:
            words.extend(option_words(param, ctx.params[param.name]))
    return " ".join(words) or "none"


def report_url(title: str) -> str:
    """The URL of the bug report form, with its title filled in."""
    return f"{ISSUES_URL}/new?{urlencode({'template': REPORT_FORM, 'title': title})}"


def render_report(
    headline: str, title: str, details: Iterable[str], sources: Counter[str]
) -> str:
    """The message inviting the user to file a bug report, with the block to paste.

    It links to the bug report form, with `title` filled in. The block opens with the
    version, the platform, the options and the formats of the sources, then gives
    the `details` of the error.
    """
    lines = [
        headline,
        "Please report it with this form:",
        report_url(title),
        (
            "Paste the lines between the two 8< markers into its Bug report field. "
            "They hold no mail content and no file path. Read the error lines first: "
            "an error message can quote a header value."
        ),
    ]
    if is_any_agent():
        lines.append(
            "AI agent: show this report to your user, and ask before you file it. "
            "GitHub issues are public."
        )
    formats = ", ".join(f"{n} {name}" for name, n in sorted(sources.items()))
    lines.extend((
        REPORT_START,
        f"mdedup {__version__}, {env_summary()}",
        f"Options: {options_summary()}",
        f"Sources: {formats or 'none'}",
        *details,
        REPORT_END,
    ))
    return "\n".join(lines)


@contextmanager
def blame(mail: DedupMailMixin, step: str) -> Generator[None, None, None]:
    """Attach the mail being processed to any error escaping the block.

    The error goes on to stop the run, and `report_unexpected_errors()` names the
    mail. It also fingerprints the mail in the bug report, except for an `OSError`,
    which gets no bug report.
    """
    try:
        yield
    except Exception as expt:
        if not hasattr(expt, FAILURE_ATTRIBUTE):
            failure = capture(expt, step, (mail,), sample=not isinstance(expt, OSError))
            setattr(expt, FAILURE_ATTRIBUTE, failure)
        raise


@contextmanager
def report_unexpected_errors(dedup: Deduplicate) -> Generator[None, None, None]:
    """End the run with a one-line error or a bug report, whatever escapes the block.

    The exceptions of Click pass through: they are how a command exits, or refuses
    an input. An `OSError` comes from the system, like a missing permission or a full
    disk, so the user can fix it: it ends the run with a one-line error. Any other
    error is a bug. Its traceback is logged with the report inviting the user to
    file it, and the run exits with code 1.
    """
    try:
        yield
    except (Abort, ClickException, Exit):
        raise
    except OSError as expt:
        logging.debug("Traceback of the error:", exc_info=expt)
        failure = getattr(expt, FAILURE_ATTRIBUTE, None)
        culprit = ""
        if failure is not None and failure.culprits:
            culprit = f" (while {failure.step} {failure.culprits[0]})"
        raise ClickException(f"{expt}{culprit}") from expt
    except Exception as expt:
        failure = getattr(expt, FAILURE_ATTRIBUTE, None) or capture(expt, dedup.step)
        culprit = f" {failure.culprits[0]}" if failure.culprits else ""
        logging.critical(
            f"Unexpected error while {failure.step}{culprit}:", exc_info=expt
        )
        logging.critical(
            render_report(
                "mdedup stopped on this error, which is a bug.",
                failure.title,
                failure_lines((failure,), f"Failure while {failure.step}"),
                dedup.source_formats,
            )
        )
        get_current_context().exit(1)
