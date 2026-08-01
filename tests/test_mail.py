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
from mail_deduplicate.mail_box import MAILDIR_SUBDIRS, BoxFormat

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


def test_decode_part_returns_non_text_payload_as_is():
    """A non-text part is passed through undecoded."""
    raw = b"Subject: s\nContent-Type: application/octet-stream\n\nraw-binary-payload\n"
    assert "raw-binary-payload" in create_mail_from_bytes(raw).body_lines


def test_decode_part_falls_back_to_utf8_without_charset():
    """A text part with no declared charset decodes via the utf-8 fallback once the
    ascii attempt fails on non-ASCII bytes."""
    raw = b"Subject: s\nContent-Type: text/plain\n\n" + "Café déjà vu\n".encode()
    assert "Café déjà vu" in create_mail_from_bytes(raw).body_lines


def test_decode_part_falls_back_to_raw_when_charset_fails():
    """When the declared charset cannot decode the bytes, the raw payload is returned
    instead of crashing."""
    payload = base64.b64encode(b"\xff\xfe not valid utf-8").decode("ascii")
    raw = (
        b"Subject: s\n"
        b'Content-Type: text/plain; charset="utf-8"\n'
        b"Content-Transfer-Encoding: base64\n"
        b"\n" + payload.encode("ascii") + b"\n"
    )
    # The undecodable payload does not raise and leaves a non-empty body.
    assert create_mail_from_bytes(raw).body_lines


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


@pytest.mark.parametrize("date_value", ["invalid date", "", "Hello, World!"])
def test_unparsable_date_returns_none(date_value):
    """An unparsable `Date` header produces no timestamp instead of crashing."""
    mail = create_mail_with_headers(("Date", date_value))
    assert mail.parsed_date is None


def test_missing_date_header_returns_none():
    """A mail without any `Date` header produces no timestamp instead of crashing."""
    mail = create_mail_with_headers(("Subject", "No date around here"))
    assert mail.parsed_date is None


def test_maildir_repr_renders_mail_file_path(make_box):
    """The repr of a maildir mail is the fully-qualified path of its own file, ready
    to be copy-pasted for direct inspection.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/157
    """
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    box = BoxFormat.MAILDIR.constructor(box_path, create=False)
    mail_id, mail = next(iter(box.iteritems()))
    mail.add_box_metadata(box, mail_id)
    box.close()

    assert repr(mail) == f"<MaildirDedupMail {mail.path}>"

    # The rendered path points to the mail's own file within the box.
    path = Path(mail.path)
    assert path.is_file()
    assert path.parent.name in MAILDIR_SUBDIRS
    assert path.parent.parent == Path(box_path)


def test_mbox_repr_appends_mail_id(make_box):
    """Mails of a file-based box all share the box's path, so their repr keeps the
    mail ID to tell them apart."""
    box_path, _, _ = make_box(mbox, [MailFactory(), MailFactory()])
    box = BoxFormat.MBOX.constructor(box_path, create=False)
    reprs = set()
    for mail_id, mail in box.iteritems():
        mail.add_box_metadata(box, mail_id)
        assert repr(mail) == f"<mboxDedupMail {box_path}:{mail_id}>"
        reprs.add(repr(mail))
    box.close()

    assert len(reprs) == 2
    assert Path(box_path).is_file()
