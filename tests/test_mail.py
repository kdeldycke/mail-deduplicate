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
import email.header
from mailbox import Maildir
from typing import Any, cast

import pytest
from extra_platforms.pytest import skip_windows  # type: ignore[attr-defined]

from mail_deduplicate.mail import DedupMailMixin

from .conftest import MailFactory, check_box


def create_mail_with_headers(
    *headers: tuple[str, str | bytes | email.header.Header],
) -> DedupMailMixin:
    """Helper to create a DedupMailMixin object with custom headers.

    Args:
        *headers: (name, value) tuples to set as mail headers.
            Values can be strings, bytes, or email.header.Header objects.
    """
    # Create minimal valid email structure
    raw_mail = b"Subject: placeholder\n\nTest body"
    msg = email.message_from_bytes(raw_mail)

    # Create a DedupMailMixin by copying the parsed message
    mail = cast(DedupMailMixin, msg)
    mail.__class__ = DedupMailMixin

    # Replace headers with provided ones
    if headers:
        cast(Any, mail)._headers = list(headers)

    return mail


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


invalid_windows_dates = skip_windows(
    reason="Invalid dates produce negative timestamps on Windows."
)
""" Some invalid dates are not supported on Windows as they produce negative
timestamps. See:
* https://github.com/arrow-py/arrow/issues/675
* https://github.com/arrow-py/arrow/pull/745
"""

invalid_date_mail_1 = MailFactory(date_rfc2822="Thu, 13 Dec 101 15:30 WET")
invalid_date_mail_2 = MailFactory(date_rfc2822="Thu, 13 Dec 102 15:30 WET")


@invalid_windows_dates
def test_invalid_date_parsing_noop(invoke, make_box):
    """Mails with strange non-standard dates gets parsed anyway and grouped into
    duplicate sets.

    No deduplication happen: mails groups shares the same metadata.
    """
    box_path, box_type, _ = make_box(
        Maildir,
        [
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )

    result = invoke("--strategy=select-newest", "--action=delete-selected", box_path)

    assert result.exit_code == 0

    check_box(
        box_path,
        box_type,
        content=[
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
        ],
    )


@invalid_windows_dates
def test_invalid_date_parsing_dedup(invoke, make_box):
    """Mails with strange non-standard dates gets parsed anyway and deduplicated if we
    reduce the source of hashed headers."""
    box_path, box_type, _ = make_box(
        Maildir,
        [
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )

    result = invoke(
        "--hash-header=message-id",
        "--hash-header=from",
        "--hash-header=to",
        "--hash-header=subject",
        "--strategy=select-newest",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0

    check_box(
        box_path,
        box_type,
        content=[
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )
