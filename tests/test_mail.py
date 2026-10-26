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

import base64
import email
import email.header
from mailbox import Maildir, mbox
from pathlib import Path
from typing import Any, cast

import pytest

from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import BoxFormat, BoxStructure

from .conftest import MailFactory


def create_mail_with_headers(
    *headers: tuple[str, str | bytes | email.header.Header],
) -> DedupMailMixin:
    """Helper to create a DedupMailMixin object with custom headers.

    :param headers: `(name, value)` tuples to set as mail headers. Values can be
        strings, bytes, or `email.header.Header` objects.
    """
    # Create minimal valid email structure
    raw_mail = b"Subject: placeholder\n\nTest body"
    msg = email.message_from_bytes(raw_mail)

    # Create a DedupMailMixin by copying the parsed message
    mail = cast(DedupMailMixin, msg)
    mail.__class__ = DedupMailMixin

    # Swapping __class__ bypasses __init__, so mirror the box metadata defaults it
    # sets, as they are required to render the mail's repr.
    mail.box = None
    mail.source_path = None
    mail.mail_id = None

    # Replace headers with provided ones
    if headers:
        cast(Any, mail)._headers = list(headers)

    return mail


def create_mail_from_bytes(raw: bytes) -> DedupMailMixin:
    """Parse raw bytes into a `DedupMailMixin`, body and all.

    Unlike `create_mail_with_headers`, this keeps the parsed payload, so the
    body-derived properties (`body_lines`, `size`, the body hashes) can be exercised.
    """
    mail = cast(DedupMailMixin, email.message_from_bytes(raw))
    mail.__class__ = DedupMailMixin
    # Swapping __class__ bypasses __init__, so mirror the box metadata defaults.
    mail.box = None
    mail.source_path = None
    mail.mail_id = None
    return mail


def test_body_hashes_distinguish_and_normalize():
    """`hash_raw_body` reflects any byte difference; `hash_normalized_body` ignores
    whitespace but still separates genuinely different bodies."""
    base = create_mail_from_bytes(b"Subject: s\n\nHello world\n")
    spaced = create_mail_from_bytes(b"Subject: s\n\nHello    world\n")
    different = create_mail_from_bytes(b"Subject: s\n\nGoodbye world\n")

    # Raw hashing: even a whitespace difference yields a different hash.
    assert base.hash_raw_body != spaced.hash_raw_body
    assert base.hash_raw_body != different.hash_raw_body

    # Normalized hashing: whitespace is stripped, so the spaced variant collapses onto
    # the base, but a real word change still differs.
    assert base.hash_normalized_body == spaced.hash_normalized_body
    assert base.hash_normalized_body != different.hash_normalized_body


def test_body_lines_gathers_multipart_preamble_and_epilogue():
    """`body_lines` collects the preamble, every leaf part and the epilogue, skipping
    the multipart container itself."""
    raw = (
        b"Subject: multi\n"
        b'Content-Type: multipart/mixed; boundary="BOUND"\n'
        b"\n"
        b"This is the preamble.\n"
        b"--BOUND\n"
        b"Content-Type: text/plain\n"
        b"\n"
        b"First part body.\n"
        b"--BOUND\n"
        b"Content-Type: text/plain\n"
        b"\n"
        b"Second part body.\n"
        b"--BOUND--\n"
        b"This is the epilogue.\n"
    )
    lines = create_mail_from_bytes(raw).body_lines

    assert "This is the preamble." in lines
    assert "First part body." in lines
    assert "Second part body." in lines
    assert "This is the epilogue." in lines


def multipart_mail(
    preamble: bytes = b"Forecast.",
    part: bytes = b"Sunny.",
    epilogue: bytes = b"End of forecast.",
) -> bytes:
    """Wrap one 8-bit `text/plain` part in a `multipart/mixed` mail."""
    return (
        b"Subject: multi\n"
        b'Content-Type: multipart/mixed; boundary="BOUND"\n'
        b"\n" + preamble + b"\n"
        b"--BOUND\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"Content-Transfer-Encoding: 8bit\n"
        b"\n" + part + b"\n"
        b"--BOUND--\n" + epilogue + b"\n"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(
            multipart_mail(preamble="台北天氣預報".encode()),
            "台北天氣預報",
            id="utf8-preamble",
        ),
        pytest.param(
            multipart_mail(epilogue="台北天氣預報".encode()),
            "台北天氣預報",
            id="utf8-epilogue",
        ),
        pytest.param(multipart_mail(part="晴天".encode()), "晴天", id="utf8-part"),
        pytest.param(
            multipart_mail(preamble=b"Forecast: 25\xb0C"),
            "Forecast: 25\N{REPLACEMENT CHARACTER}C",
            id="latin1-preamble",
        ),
        pytest.param(
            multipart_mail(epilogue=b"Forecast: 25\xb0C"),
            "Forecast: 25\N{REPLACEMENT CHARACTER}C",
            id="latin1-epilogue",
        ),
        pytest.param(
            b"Subject: s\n"
            b"Content-Type: application/octet-stream\n"
            b"\n"
            b"raw-binary-payload\n",
            "raw-binary-payload",
            id="non-text-part-as-is",
        ),
        # The ASCII attempt fails on non-ASCII bytes, the UTF-8 one does not.
        pytest.param(
            b"Subject: s\nContent-Type: text/plain\n\n" + "Café déjà vu\n".encode(),
            "Café déjà vu",
            id="no-charset-utf8-fallback",
        ),
        pytest.param(
            b"Subject: s\n"
            b'Content-Type: text/plain; charset="utf-8"\n'
            b"Content-Transfer-Encoding: base64\n"
            b"\n" + base64.b64encode(b"\xff\xfe not valid utf-8") + b"\n",
            base64.b64encode(b"\xff\xfe not valid utf-8").decode("ascii"),
            id="charset-fails-raw-payload",
        ),
    ],
)
def test_body_lines_decodes_each_part(raw, expected):
    """Every part of a mail is decoded into its body lines, whatever its bytes, and
    both body hashes are computed from them.

    The parser keeps each non-ASCII byte as a lone surrogate. `get_payload()` decodes
    the parts, and `body_lines` decodes the preamble and epilogue as UTF-8, instead of
    leaving surrogates that crash both body hashes with a `UnicodeEncodeError`. A byte
    that is not valid UTF-8 becomes `U+FFFD`.

    A non-text part is passed through undecoded. A text part with no charset is tried
    as ASCII, then as UTF-8. A text part its charset cannot decode comes back as its
    raw payload instead of crashing.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/1085
    """
    mail = create_mail_from_bytes(raw)

    assert expected in mail.body_lines
    assert mail.hash_raw_body
    assert mail.hash_normalized_body


@pytest.mark.parametrize(
    ("header_name", "values", "expected"),
    [
        # === Basic string normalization ===
        pytest.param(
            "Custom-Header",
            ["  value  with   spaces  "],
            ["value with spaces"],
            id="basic-whitespace-normalization",
        ),
        pytest.param(
            "Custom",
            ["\t\n  value  \t\n"],
            ["value"],
            id="whitespace-tabs-newlines-normalized",
        ),
        pytest.param(
            "Custom",
            ["word1   word2\t\tword3\n\nword4"],
            ["word1 word2 word3 word4"],
            id="inner-whitespace-collapsed",
        ),
        # === Type conversions ===
        pytest.param(
            "Custom",
            [email.header.Header("test value")],
            ["test value"],
            id="email-header-object-conversion",
        ),
        pytest.param(
            "Custom",
            [email.header.Header("encoded: äöü", "utf-8")],
            ["encoded: äöü"],
            id="email-header-unicode-decoded",
        ),
        pytest.param(
            "Custom",
            [b"byte value"],
            ["byte value"],
            id="bytes-to-string-conversion",
        ),
        pytest.param(
            "Custom",
            [b"\xff\xfe invalid utf-8"],
            ["\ufffd\ufffd invalid utf-8"],
            id="bytes-invalid-utf8-replaced",
        ),
        # === Empty/missing value filtering ===
        pytest.param(
            "X-Nonexistent",
            [],
            [],
            id="nonexistent-header-returns-empty",
        ),
        pytest.param(
            "Subject",
            [""],
            [],
            id="subject-empty-filtered",
        ),
        pytest.param(
            "Custom",
            ["   ", "valid"],
            ["valid"],
            id="empty-values-filtered",
        ),
        pytest.param(
            "Custom",
            ["", "   ", "\t", "valid"],
            ["valid"],
            id="multiple-empty-values-filtered",
        ),
        # === Multiple header occurrences ===
        pytest.param(
            "Received",
            ["server1", "server2"],
            ["server1", "server2"],
            id="multiple-occurrences",
        ),
        # === Subject normalization ===
        pytest.param(
            "Subject",
            ["Simple subject no prefix"],
            ["Simple subject no prefix"],
            id="subject-no-prefix-unchanged",
        ),
        pytest.param(
            "Subject",
            ["Re: Simple reply"],
            ["Simple reply"],
            id="subject-re-prefix",
        ),
        pytest.param(
            "Subject",
            ["Re: Re: [list] Test"],
            ["Test"],
            id="subject-multiple-re-prefixes",
        ),
        pytest.param(
            "Subject",
            ["RE: RE: RE: Important"],
            ["Important"],
            id="subject-uppercase-re-prefixes",
        ),
        pytest.param(
            "Subject",
            ["Re:No space after colon"],
            ["Re:No space after colon"],
            id="subject-re-no-space-unchanged",
        ),
        pytest.param(
            "Subject",
            ["Fw: Forwarded message"],
            ["Forwarded message"],
            id="subject-fw-prefix-short-form",
        ),
        pytest.param(
            "Subject",
            ["Fwd: [list] Re: [other-list] Topic"],
            ["Topic"],
            id="subject-fwd-with-list-prefixes",
        ),
        pytest.param(
            "Subject",
            ["FWD: FW: Re: RE: [list] Topic"],
            ["Topic"],
            id="subject-mixed-case-prefixes",
        ),
        pytest.param(
            "Subject",
            ["[list] Message"],
            ["Message"],
            id="subject-single-list-prefix",
        ),
        pytest.param(
            "Subject",
            ["[list-name] [another-list] Re: Actual subject"],
            ["Actual subject"],
            id="subject-mailing-list-prefix",
        ),
        pytest.param(
            "Subject",
            ["[a] Single char list"],
            ["Single char list"],
            id="subject-single-char-list-stripped",
        ),
        pytest.param(
            "Subject",
            ["[ab] Two char list"],
            ["Two char list"],
            id="subject-two-char-list-stripped",
        ),
        pytest.param(
            "Subject",
            ["[list-with-dash] Topic"],
            ["Topic"],
            id="subject-list-with-dash-stripped",
        ),
        pytest.param(
            "Subject",
            ["[list_with_underscore] Topic"],
            ["Topic"],
            id="subject-list-with-underscore-stripped",
        ),
        pytest.param(
            "Subject",
            ["[123numericlist] Topic"],
            ["Topic"],
            id="subject-list-starting-with-number",
        ),
        # === Content-Type normalization ===
        pytest.param(
            "Content-Type",
            ["text/html"],
            ["text/html"],
            id="content-type-no-params-unchanged",
        ),
        pytest.param(
            "Content-Type",
            ['text/plain; charset="utf-8"; boundary="xyz"'],
            ["text/plain"],
            id="content-type-strips-parameters",
        ),
        pytest.param(
            "Content-Type",
            ["text/plain;charset=utf-8"],
            ["text/plain"],
            id="content-type-no-space-after-semicolon",
        ),
        pytest.param(
            "Content-Type",
            ["multipart/mixed; boundary=abc123"],
            ["multipart/mixed"],
            id="content-type-strips-boundary",
        ),
        # === Date normalization ===
        pytest.param(
            "Date",
            ["Mon, 15 Jan 2024 10:30:45 +0000"],
            ["2024-01-15"],
            id="date-normalization",
        ),
        pytest.param(
            "Date",
            ["15 Jan 2024 10:30:45 -0500"],
            ["2024-01-15"],
            id="date-different-timezone",
        ),
        pytest.param(
            "Date",
            ["invalid date string"],
            ["invalid date string"],
            id="date-invalid-unchanged",
        ),
        # === Address header normalization (quotes removal) ===
        pytest.param(
            "From",
            ["user@example.com"],
            ["user@example.com"],
            id="from-plain-address-unchanged",
        ),
        pytest.param(
            "From",
            ['"John Doe" <john@example.com>'],
            ["John Doe <john@example.com>"],
            id="from-address-removes-quotes",
        ),
        pytest.param(
            "From",
            ['  "  Spaced Name  "  <user@example.com>  '],
            ["Spaced Name <user@example.com>"],
            id="from-extra-spaces-normalized",
        ),
        pytest.param(
            "From",
            ['""Empty Name"" <user@example.com>'],
            ["Empty Name <user@example.com>"],
            id="from-double-quotes-removed",
        ),
        pytest.param(
            "From",
            ["user@example.com (Comment)"],
            ["user@example.com (Comment)"],
            id="from-parenthetical-comment-preserved",
        ),
        pytest.param(
            "Cc",
            ['"Alice" <alice@example.com>, "Bob" <bob@example.com>'],
            ["Alice <alice@example.com>, Bob <bob@example.com>"],
            id="cc-multiple-addresses",
        ),
        pytest.param(
            "Bcc",
            ['"Hidden User" <hidden@example.com>'],
            ["Hidden User <hidden@example.com>"],
            id="bcc-address-normalization",
        ),
        pytest.param(
            "Reply-To",
            ['"Support Team" <support@example.com>'],
            ["Support Team <support@example.com>"],
            id="reply-to-address-normalization",
        ),
        pytest.param(
            "Sender",
            ['"Admin" <admin@example.com>'],
            ["Admin <admin@example.com>"],
            id="sender-address-normalization",
        ),
        pytest.param(
            "Return-Path",
            ['"Bounce" <bounce@example.com>'],
            ["Bounce <bounce@example.com>"],
            id="return-path-address-normalization",
        ),
        pytest.param(
            "Delivered-To",
            ['"User" <user@example.com>'],
            ["User <user@example.com>"],
            id="delivered-to-address-normalization",
        ),
        pytest.param(
            "X-Original-To",
            ['"Recipient" <rcpt@example.com>'],
            ["Recipient <rcpt@example.com>"],
            id="x-original-to-address-normalization",
        ),
        pytest.param(
            "Resent-From",
            ['"Resender" <resend@example.com>'],
            ["Resender <resend@example.com>"],
            id="resent-from-address-normalization",
        ),
        pytest.param(
            "Envelope-To",
            ['"Envelope" <env@example.com>'],
            ["Envelope <env@example.com>"],
            id="envelope-to-address-normalization",
        ),
        pytest.param(
            "X-Envelope-From",
            ['"X-Env" <xenv@example.com>'],
            ["X-Env <xenv@example.com>"],
            id="x-envelope-from-address-normalization",
        ),
        pytest.param(
            "Original-Recipient",
            ['"Original" <orig@example.com>'],
            ["Original <orig@example.com>"],
            id="original-recipient-address-normalization",
        ),
        pytest.param(
            "Disposition-Notification-To",
            ['"Notify" <notify@example.com>'],
            ["Notify <notify@example.com>"],
            id="disposition-notification-to-normalization",
        ),
        # === To header (address + angle bracket stripping) ===
        pytest.param(
            "To",
            ["user@example.com"],
            ["user@example.com"],
            id="to-plain-address-unchanged",
        ),
        pytest.param(
            "To",
            ["<test@example.com>"],
            ["test@example.com"],
            id="to-strips-angle-brackets",
        ),
        pytest.param(
            "To",
            ["<a@b>"],
            ["a@b"],
            id="to-minimal-address-stripped",
        ),
        pytest.param(
            "To",
            ["<>"],
            ["<>"],
            id="to-empty-brackets-preserved",
        ),
        pytest.param(
            "To",
            ["<user@example.com>, <other@example.com>"],
            ["<user@example.com>, <other@example.com>"],
            id="to-multiple-addresses-brackets-kept",
        ),
        # === Message-ID normalization (angle bracket stripping) ===
        pytest.param(
            "Message-ID",
            ["unique-id@example.com"],
            ["unique-id@example.com"],
            id="message-id-no-brackets-unchanged",
        ),
        pytest.param(
            "Message-ID",
            ["<unique-id@example.com>"],
            ["unique-id@example.com"],
            id="message-id-strips-brackets",
        ),
        pytest.param(
            "Message-ID",
            ["<msg-123@domain.com>"],
            ["msg-123@domain.com"],
            id="message-id-complex-brackets",
        ),
        pytest.param(
            "Message-ID",
            ["no-brackets@domain.com"],
            ["no-brackets@domain.com"],
            id="message-id-plain-unchanged",
        ),
        pytest.param(
            "Message-ID",
            ["<multi,part@domain.com>"],
            ["<multi,part@domain.com>"],
            id="message-id-comma-brackets-kept",
        ),
        pytest.param(
            "Message-ID",
            ["<nested<brackets>@domain.com>"],
            ["<nested<brackets>@domain.com>"],
            id="message-id-nested-brackets-preserved",
        ),
    ],
)
def test_header_normalization(header_name, values, expected):
    """Test header value normalization."""
    headers = [(header_name, v) for v in values]
    mail = create_mail_with_headers(*headers)
    result = list(mail.normalized_header_values(header_name.lower()))
    assert result == expected


@pytest.mark.parametrize(
    "header",
    (
        pytest.param(("Date", "invalid date"), id="invalid-date"),
        pytest.param(("Date", ""), id="empty-date"),
        pytest.param(("Date", "Hello, World!"), id="greeting-date"),
        pytest.param(("Subject", "No date around here"), id="no-date-header"),
    ),
)
def test_unparsable_date_returns_none(header):
    """A missing or unparsable `Date` header produces no timestamp instead of
    crashing."""
    mail = create_mail_with_headers(header)
    assert mail.parsed_date is None


@pytest.mark.parametrize("box_format", tuple(BoxFormat), ids=str)
def test_mail_path_derived_from_box(make_box, box_format):
    """A mail's location comes from its box's own index, not from opening its file,
    and its repr renders that location, ready to be copy-pasted for inspection.

    Folder-based boxes give every mail its own file, so their mails carry distinct
    paths below the box's directory, which their repr shows. File-based boxes pack
    every mail into the box's single file, so their mails all share its path, and
    their repr adds the mail ID to tell them apart.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/157
    """
    box_path, _, _ = make_box(box_format.base_class, [MailFactory(), MailFactory()])
    box = box_format.constructor(box_path, create=False)

    paths = []
    reprs = set()
    for mail_id, mail in box.iteritems():
        mail.add_box_metadata(box, mail_id)
        paths.append(mail.path)
        reprs.add(repr(mail))
        name = type(mail).__name__
        if box_format.structure is BoxStructure.FOLDER:
            assert repr(mail) == f"<{name} {mail.path}>"
        else:
            assert repr(mail) == f"<{name} {box_path}:{mail_id}>"
    box.close()

    assert len(paths) == 2
    assert len(reprs) == 2
    # Whatever the layout, the path points at something readable on disk.
    assert all(Path(path).is_file() for path in paths)

    if box_format.structure is BoxStructure.FOLDER:
        assert len(set(paths)) == 2
        for path in paths:
            assert Path(path) != Path(box_path)
            assert Path(box_path) in Path(path).parents
    else:
        assert set(paths) == {box_path}


def load_single_mail(make_box, config, box_type):
    """Helper returning the single mail of a fresh test box, ready for dedup work."""
    box_format = next(fmt for fmt in BoxFormat if fmt.base_class is box_type)
    box_path, _, _ = make_box(box_type, [MailFactory()])
    box = box_format.constructor(box_path, create=False)
    mail_id, mail = next(iter(box.iteritems()))
    mail.add_box_metadata(box, mail_id)
    mail.conf = config
    return box, mail_id, mail


@pytest.mark.parametrize("box_type", (Maildir, mbox))
def test_dehydrate_hydrate_roundtrip(make_box, config, box_type):
    """Dehydration must drop the parsed message but keep the scalars used by the
    selection strategies, and content-dependent properties must transparently
    restore the exact same content from the source box.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/761
    """
    box, _, mail = load_single_mail(make_box, config, box_type)

    original_text = str(mail)
    original_body = mail.body_lines

    mail.dehydrate()

    assert not mail.is_hydrated
    assert not hasattr(mail, "_headers")
    assert not hasattr(mail, "_payload")
    # Scalars needed by strategies survive without the parsed message. Size was
    # memoized for free since the decoded body was at hand.
    assert "timestamp" in vars(mail)
    assert "size" in vars(mail)
    # Content caches are gone.
    assert "body_lines" not in vars(mail)
    assert "canonical_headers" not in vars(mail)

    # Dehydrating twice is a no-op.
    mail.dehydrate()

    # Content-dependent properties transparently re-read the message from the box.
    assert mail.body_lines == original_body
    assert mail.is_hydrated
    assert str(mail) == original_text
    box.close()


@pytest.mark.parametrize("box_type", (Maildir, mbox))
def test_dehydrated_mail_defers_body_reads(make_box, config, box_type):
    """A mail dehydrated before its body was ever decoded must re-read its message
    from the source box on the first body-dependent access."""
    box, mail_id, mail = load_single_mail(make_box, config, box_type)
    twin = box[mail_id]
    twin.conf = config

    mail.dehydrate()

    # The body was never decoded, so its derived size was not memoized either.
    assert "size" not in vars(mail)
    assert "body_lines" not in vars(mail)

    assert mail.size == len("".join(twin.body_lines))
    assert mail.is_hydrated
    box.close()
