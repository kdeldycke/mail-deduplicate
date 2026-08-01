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

"""End-to-end behavior of mail parsing, timestamps and hashing driven through the
`mdedup` CLI. Unit-level tests of the mail object live in `test_mail.py`."""

from __future__ import annotations

import time
from mailbox import Maildir, mbox, mboxMessage
from textwrap import dedent

import pytest
from extra_platforms.pytest import skip_windows

from .conftest import MailFactory, check_box

invalid_windows_dates = skip_windows(
    reason="Invalid dates produce negative timestamps on Windows."
)
# Some invalid dates are not supported on Windows as they produce negative
# timestamps. See:
# https://github.com/arrow-py/arrow/issues/675
# https://github.com/arrow-py/arrow/pull/745

# The `Thu, 13 Dec 101 15:30 WET` header comes from a real non-y2k-compliant mailer
# that once made the tool crash with "ValueError: year out of range". See:
# https://github.com/kdeldycke/mail-deduplicate/issues/54
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


undated_mail = MailFactory(date_rfc2822="invalid date")
"""A mail whose `Date` header cannot be parsed into a timestamp."""


def test_missing_date_header_skips_time_strategy(invoke, tmp_path):
    """Duplicate mails without any `Date` header, as saved into mbox files by some
    clients, are skipped by time-based strategies instead of crashing. The run also
    names the offending mail rather than failing the whole mailbox silently.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/600 and
    https://github.com/kdeldycke/mail-deduplicate/issues/954
    """
    dateless_mail = dedent("""\
        X-Mozilla-Status: 0001
        X-Mozilla-Status2: 00000000
        MIME-Version: 1.0
        From: "Mailbox Support" <support@example.com>
        To: "Joseph Turian" <joseph@example.com>
        Subject: Tips for Using Mailbox in Gmail
        Content-Type: text/plain; charset=utf-8

        Hi Joseph,
        """)
    box_path = tmp_path / "dateless.mbox"
    box = mbox(str(box_path))
    for _ in range(2):
        box.add(mboxMessage(dateless_mail))
    box.flush()
    box.close()

    result = invoke(
        "--strategy=select-oldest", "--action=delete-selected", str(box_path)
    )

    assert result.exit_code == 0
    assert "cannot compare mails without a timestamp" in result.stderr
    assert "No timestamp for <mboxDedupMail" in result.stderr

    # No mail was removed.
    box = mbox(str(box_path), create=False)
    assert len(box) == 2
    box.close()


def test_unparsable_date_skips_time_strategy(invoke, make_box):
    """Time-based strategies skip duplicate sets containing mails without a parseable
    `Date` header, and name the offending mails instead of crashing.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/132
    """
    box_path, box_type, _ = make_box(Maildir, [undated_mail, undated_mail])

    result = invoke("--strategy=select-oldest", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    assert "cannot compare mails without a timestamp" in result.stderr
    assert "No timestamp for <MaildirDedupMail" in result.stderr

    # No mail was removed.
    check_box(box_path, box_type, content=[undated_mail, undated_mail])


def test_mixed_missing_date_skips_time_strategy(invoke, make_box):
    """A single mail without a parseable `Date` header is enough to skip its whole
    set when a time-based strategy is applied."""
    dated_mail = MailFactory(date="2021-01-01")
    box_path, box_type, _ = make_box(Maildir, [undated_mail, dated_mail])

    result = invoke(
        # Remove the date from the hashed headers so both mails are grouped in the
        # same duplicate set.
        "--hash-header=message-id",
        "--hash-header=from",
        "--hash-header=to",
        "--hash-header=subject",
        "--strategy=select-newest",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0
    assert "cannot compare mails without a timestamp" in result.stderr
    assert "No timestamp for <MaildirDedupMail" in result.stderr

    # No mail was removed.
    check_box(box_path, box_type, content=[undated_mail, dated_mail])


def test_unparsable_date_show_diff(invoke, make_box):
    """Rendering the diff of mails without a parseable `Date` header does not
    crash."""
    undated_variant = MailFactory(date_rfc2822="invalid date", body="A different body.")
    box_path, box_type, _ = make_box(Maildir, [undated_mail, undated_variant])

    result = invoke(
        "--content-threshold=0",
        "--show-diff",
        "--strategy=select-oldest",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0
    assert "mails are too dissimilar in content" in result.stderr

    # No mail was removed.
    check_box(box_path, box_type, content=[undated_mail, undated_variant])


@pytest.mark.parametrize(
    ("hash_body", "deduplicated"),
    (
        pytest.param("skip", True, id="skip-ignores-body"),
        pytest.param("raw", False, id="raw-separates-differing-bodies"),
    ),
)
def test_hash_body_skip_vs_raw(invoke, make_box, hash_body, deduplicated):
    """--hash-body=skip groups mails by their headers alone, so two mails with
    identical headers but different bodies are duplicates; =raw folds the body into
    the hash, so they no longer are."""
    a = MailFactory(date="2021-01-01", message_id="<hb@nohost.com>", body="Body A.\n")
    b = MailFactory(
        date="2021-01-01", message_id="<hb@nohost.com>", body="A different body B.\n"
    )
    box_path, _, _ = make_box(Maildir, [a, b])

    result = invoke(
        f"--hash-body={hash_body}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert len(Maildir(box_path, create=False)) == (1 if deduplicated else 2)


@pytest.mark.parametrize(
    ("hash_body", "deduplicated"),
    (
        pytest.param("raw", False, id="raw-keeps-whitespace-variants-apart"),
        pytest.param("normalized", True, id="normalized-folds-whitespace-variants"),
    ),
)
def test_hash_body_raw_vs_normalized(invoke, make_box, hash_body, deduplicated):
    """--hash-body=normalized ignores whitespace-only body differences that =raw
    treats as distinct."""
    a = MailFactory(
        date="2021-01-01", message_id="<n@nohost.com>", body="Hello world\n"
    )
    b = MailFactory(
        date="2021-01-01", message_id="<n@nohost.com>", body="Hello   world\n"
    )
    box_path, _, _ = make_box(Maildir, [a, b])

    result = invoke(
        f"--hash-body={hash_body}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert len(Maildir(box_path, create=False)) == (1 if deduplicated else 2)


def test_ctime_time_source(invoke, make_box):
    """--time-source=ctime derives each mail's timestamp from its file's inode change
    time, so a maildir with distinct file ctimes deduplicates by them."""
    dup = MailFactory(body="Same body.\n", message_id="<ctime@nohost.com>")

    # Deliver the two identical copies more than a second apart, so the second file is
    # unambiguously the newest by ctime at any filesystem timestamp resolution. A
    # sub-second gap ties on coarse-grained filesystems (e.g. overlayfs, 1 s), and on
    # Windows getctime reads the immutable creation time, so touching a file's metadata
    # in place (chmod) cannot reorder the copies there.
    box_path, _, _ = make_box(Maildir, [dup])
    time.sleep(1.1)
    box = Maildir(box_path, create=False)
    box.lock()
    box.add(dup.render())
    box.close()

    result = invoke(
        "--time-source=ctime",
        "--strategy=select-newest",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0
    # The newest copy (delivered last) was selected and deleted; one copy remains.
    assert len(Maildir(box_path, create=False)) == 1


def test_mail_rejected_when_too_few_headers(invoke, tmp_path):
    """A mail carrying fewer than the minimal hashable headers is rejected, not
    hashed, and left untouched, instead of crashing the whole run.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/27
    """
    box_path = str(tmp_path / "box")
    box = Maildir(box_path, create=True)
    # Subject is the only default hash header present, below the floor of 4.
    box.add(b"Subject: lonely mail\n\nA body.\n")
    box.close()

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "Rejecting" in result.stderr
    # Nothing was hashed, so nothing is removed.
    assert len(Maildir(box_path, create=False)) == 1


def test_crlf_and_lf_bodies_are_duplicates(invoke, tmp_path):
    """Two mails identical but for LF vs CRLF line endings are recognized as
    duplicates: line endings must not count toward size or content differences.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/844 (fixed by PR 845).
    """
    headers = (
        b"Date: Mon, 15 Jan 2024 10:30:45 +0000\n"
        b"From: foo@bar.com\n"
        b"To: baz@qux.com\n"
        b"Subject: Line endings\n"
        b"Message-ID: <crlf@nohost.com>\n"
        b"Content-Type: text/plain\n"
        b"\n"
    )
    body = b"Line one\nLine two\nLine three\n"

    box_path = str(tmp_path / "box")
    box = Maildir(box_path, create=True)
    box.add(headers + body)  # LF throughout.
    box.add(headers.replace(b"\n", b"\r\n") + body.replace(b"\n", b"\r\n"))  # CRLF.
    box.close()

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "too dissimilar" not in result.stderr
    # The CRLF and LF copies collapsed into a single duplicate set; one copy remains.
    assert len(Maildir(box_path, create=False)) == 1
