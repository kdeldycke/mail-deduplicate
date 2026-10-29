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

import os
from mailbox import Maildir, mbox
from pathlib import Path
from string import ascii_lowercase

import pytest

from mail_deduplicate.action import LINK_TEMP_PREFIX, OPERATIONS, Action
from mail_deduplicate.deduplicate import Deduplicate, Stat
from mail_deduplicate.mail_box import EML, BoxFormat

from .conftest import MailFactory, check_box, mail_files

PARTLESS_HEADERS = (
    b"Date: Thu, 11 Oct 2018 09:30:00 +0800\r\n"
    b"From: Clementine <clementine@orchard.example>\r\n"
    b"To: quince@orchard.example\r\n"
    b"Subject: Weather in Taipei\r\n"
    b"Message-ID: <taipei-weather@orchard.example>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/alternative; boundary="Kiwi-Boundary"\r\n'
    b"\r\n"
)
"""Headers of a multipart mail whose body never opens with its boundary, so it
parses with no subpart."""


@pytest.mark.parametrize("action", Action, ids=str)
def test_action_definition(action):
    """Test duplicate action definitions."""
    assert isinstance(action.value, str)
    assert set(action.value).issubset(ascii_lowercase + "-")
    assert str(action) == action.value
    assert action.name.lower().replace("_", "-") == action.value

    # Every action decomposes into a registered operation and a target subset.
    operation = OPERATIONS[action.verb]
    assert callable(operation)
    assert operation.__name__ == f"{action.verb}_mails"
    assert action.value == (
        f"{action.verb}-discarded"
        if action.acts_on_discarded
        else f"{action.verb}-selected"
    )

    # Only a destructive action on the selection can lose a mail that has no
    # duplicate, so it is the only one sparing them. Pinned over every member so a
    # new destructive `*-selected` action cannot silently bring back
    # https://github.com/kdeldycke/mail-deduplicate/issues/1053.
    assert action.spares_unique == (
        action.verb == "delete" and not action.acts_on_discarded
    )


duplicate_mail = MailFactory(body="Shared duplicate body.\n")
unique_mail = MailFactory(
    message_id="<no-copies-anywhere@example.com>", body="Unique body.\n"
)

# A box of three copies plus one unique mail. Under select-one, one copy is kept, so
# the selection is {unique, one copy} and the discard is {two copies}. The counts stay
# distinct (2 vs 2 vs 4), so no metric coincidentally equals another in the self-check.
FULL_BOX = [duplicate_mail, duplicate_mail, duplicate_mail, unique_mail]
SELECTION = [duplicate_mail, unique_mail]
"""Mails the selection resolves to: the unique mail plus one surviving copy."""
DISCARD = [duplicate_mail, duplicate_mail]
"""Mails the discard resolves to: the two other copies."""
DISCARD_AND_UNIQUE = [*DISCARD, unique_mail]
"""What a `delete-selected` run leaves behind.

The mail that has no duplicate belongs to the selection, but deleting it would leave
no copy of it anywhere, so only the copy the strategy picked is removed. See:
https://github.com/kdeldycke/mail-deduplicate/issues/1053
"""


@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry_run"])
@pytest.mark.parametrize(
    ("action", "needs_export", "source_after", "export_after"),
    (
        pytest.param("copy-selected", True, FULL_BOX, SELECTION, id="copy-selected"),
        pytest.param("copy-discarded", True, FULL_BOX, DISCARD, id="copy-discarded"),
        pytest.param("move-selected", True, DISCARD, SELECTION, id="move-selected"),
        pytest.param("move-discarded", True, SELECTION, DISCARD, id="move-discarded"),
        pytest.param(
            "delete-selected", False, DISCARD_AND_UNIQUE, None, id="delete-selected"
        ),
        pytest.param("delete-discarded", False, SELECTION, None, id="delete-discarded"),
        # Hardlinking keeps every mail in place: the copies are identical here, so
        # the box reads exactly as it did before, whatever backs its mails.
        pytest.param(
            "hardlink-discarded", False, FULL_BOX, None, id="hardlink-discarded"
        ),
    ),
)
def test_action_matrix(
    invoke, make_box, action, needs_export, source_after, export_after, dry_run
):
    """Every action lands the right mails in the right box, and the stats self-check
    stays consistent, in real and dry-run mode alike.

    Copy actions leave the source intact; move and delete actions strip it down to
    whichever subset they did not act on, with `delete-selected` also leaving the
    mail that has no duplicate. Export actions also cover the re-reading of
    full messages from the source boxes, as mails are dehydrated to lightweight stubs
    once hashed: a regression there would export empty or truncated mails.
    """
    box_path, box_type, export_path = make_box(Maildir, FULL_BOX)

    args = ["--strategy=select-one", f"--action={action}", box_path]
    if needs_export:
        args.append(f"--export={export_path}")
    if dry_run:
        args.insert(0, "--dry-run")
    result = invoke(*args)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr

    if dry_run:
        # Nothing is touched: source intact and no export box created.
        check_box(box_path, box_type, content=FULL_BOX)
        if needs_export:
            assert not Path(export_path).exists()
    else:
        check_box(box_path, box_type, content=source_after)
        if needs_export:
            check_box(export_path, mbox, content=export_after)


@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry_run"])
@pytest.mark.parametrize(
    ("action", "needs_export", "box_type", "outcome"),
    (
        pytest.param("copy-discarded", True, Maildir, "copied", id="copy"),
        pytest.param("move-discarded", True, Maildir, "moved", id="move"),
        pytest.param("delete-discarded", False, Maildir, "deleted", id="delete"),
        pytest.param("hardlink-discarded", False, Maildir, "hardlinked", id="hardlink"),
        # Mails of a file-based box have no file of their own to link.
        pytest.param("hardlink-discarded", False, mbox, "skipped", id="hardlink-skip"),
    ),
)
def test_trail_lines_tell_a_dry_run_apart(
    invoke, make_box, action, needs_export, box_type, outcome, dry_run
):
    """Each mail's line reports what happened to it in a real run only.

    A dry run touches no mail, so its lines say what would have happened instead of
    reading like the record of a run that went through.
    """
    box_path, _, export_path = make_box(box_type, FULL_BOX)

    args = ["--strategy=select-one", f"--action={action}", box_path]
    if needs_export:
        args.append(f"--export={export_path}")
    if dry_run:
        args.insert(0, "--dry-run")
    result = invoke(*args)

    assert result.exit_code == 0
    # A mail's repr closes on `>`, which anchors the wording that follows it.
    lines = [line for line in result.stderr.splitlines() if line[:3] in ("✓ <", "✘ <")]
    assert len(lines) == len(DISCARD)
    expected = f"> would be {outcome}" if dry_run else f"> {outcome}"
    assert all(line.endswith(expected) for line in lines), lines


@pytest.mark.parametrize("box_type", [Maildir, mbox], ids=["maildir", "mbox"])
def test_trail_lists_mails_in_a_stable_order(invoke, make_box, box_type):
    """The action trail lists its mails in the same order on every run.

    The targets of an action are a set, whose iteration order changes from one
    process to the next: left unsorted, two runs on the same boxes printed the
    same lines in different orders, which no diff of two runs survives. The order
    the run sorts them by is the one a reader compares two runs with: the box
    path, then the mail's ID within it.
    """
    box_path, _, export_path = make_box(box_type, [duplicate_mail] * 4)
    result = invoke(
        "--strategy=select-one",
        "--action=copy-discarded",
        box_path,
        f"--export={export_path}",
    )

    assert result.exit_code == 0
    # Four identical copies: select-one keeps one, so three are discarded, which
    # is enough trail lines for a set order to differ from the sorted one.
    lines = [line for line in result.stderr.splitlines() if line[:3] == "✓ <"]
    assert len(lines) == 3
    assert lines == sorted(lines)


@pytest.mark.parametrize("jobs", [1, 2], ids=["sequential", "parallel"])
def test_delete_selected_spares_mails_without_duplicates(invoke, make_box, jobs):
    """A mail that has no duplicate survives a `delete-selected` run that has nothing
    else to act on.

    The two copies here differ by far more than the default size threshold, as a mail
    carrying an attachment differs from the same mail without one. Their set is
    skipped, which leaves the selection made of the mail that has no duplicate alone.
    Deleting the whole selection then wipes the one mail the run was never asked to
    touch, and keeps the two it was. Covers both the sequential and the parallel
    selection paths, as each merges its own verdict back. See:
    https://github.com/kdeldycke/mail-deduplicate/issues/1053
    """
    plain_copy = MailFactory(
        message_id="<newsletter@example.com>", body="Weather report for today.\n"
    )
    copy_with_attachment = MailFactory(
        message_id="<newsletter@example.com>",
        body="Weather report for today. " + "attachment payload " * 200 + "\n",
    )
    box_path, box_type, _ = make_box(
        Maildir, [plain_copy, copy_with_attachment, unique_mail]
    )

    result = invoke(
        f"--jobs={jobs}",
        "--strategy=select-all-but-one",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    assert "too dissimilar in size" in result.stderr
    assert "left untouched: they have no duplicate" in result.stderr
    check_box(
        box_path, box_type, content=[plain_copy, copy_with_attachment, unique_mail]
    )


def test_assert_stats_consistent_passes(config):
    """A satisfied assertion returns quietly, without exiting."""
    dedup = Deduplicate(config)
    dedup.stats[Stat.MAIL_FOUND] = 5
    dedup.stats[Stat.MAIL_RETAINED] = 3

    dedup.assert_stats(Stat.MAIL_FOUND, ">=", Stat.MAIL_RETAINED)


def inodes(box_path) -> set[int]:
    """The distinct files backing the mails of a folder-based box.

    One inode per mail before any linking, one per group of linked copies after.
    """
    return {path.stat().st_ino for path in mail_files(box_path)}


@pytest.mark.parametrize("jobs", [1, 2], ids=["sequential", "parallel"])
def test_hardlink_discarded_collapses_copies_onto_one_file(invoke, make_box, jobs):
    """Discarded copies keep their own name and place, but end up backed by the file
    of the copy kept in their set, while the unique mail keeps a file to itself.

    Runs over both selection paths: pairing each discarded mail with the copy it is
    linked to is recorded per duplicate set, which a parallel run settles in worker
    processes and merges back afterwards.
    """
    box_path, box_type, _ = make_box(Maildir, FULL_BOX)
    before = mail_files(box_path)
    assert len(inodes(box_path)) == len(FULL_BOX)

    result = invoke(
        f"--jobs={jobs}",
        "--strategy=select-one",
        "--action=hardlink-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    # The three copies share a single file, the unique mail keeps its own.
    assert len(inodes(box_path)) == 2
    # No mail was added, removed or renamed: only what backs them changed.
    assert mail_files(box_path) == before
    check_box(box_path, box_type, content=FULL_BOX)


def test_hardlink_discarded_dry_run_leaves_files_alone(invoke, make_box):
    """A dry run reports on the links it would create without creating any."""
    box_path, box_type, _ = make_box(Maildir, FULL_BOX)
    before = {path: path.stat().st_ino for path in mail_files(box_path)}

    result = invoke(
        "--dry-run", "--strategy=select-one", "--action=hardlink-discarded", box_path
    )

    assert result.exit_code == 0
    assert {path: path.stat().st_ino for path in mail_files(box_path)} == before
    check_box(box_path, box_type, content=FULL_BOX)


DIFFERING_COPIES = [
    MailFactory(body="Slightly different body.\n"),
    MailFactory(body="Slightly different bodies.\n"),
]
"""Two mails sharing a hash, as the body is left out of it by default, but backed by
files differing byte for byte."""


@pytest.mark.parametrize(
    ("extra_args", "distinct_files"),
    (
        pytest.param((), 2, id="left-alone-by-default"),
        pytest.param(("--hardlink-differing",), 1, id="linked-on-demand"),
    ),
)
def test_hardlink_discarded_gates_on_byte_equality(
    invoke, make_box, extra_args, distinct_files
):
    """Copies that are not byte-for-byte identical are only linked when asked for,
    as linking swaps the discarded mail's own content for the kept copy's.
    """
    box_path, _, _ = make_box(Maildir, DIFFERING_COPIES)

    result = invoke(
        "--strategy=select-one",
        "--action=hardlink-discarded",
        *extra_args,
        box_path,
    )

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    assert len(inodes(box_path)) == distinct_files

    box = Maildir(box_path, create=False)
    found = {str(mail) for mail in box}
    box.close()
    originals = {str(mail.as_message()) for mail in DIFFERING_COPIES}
    if extra_args:
        # Both mails now read as whichever copy the selection kept.
        assert found < originals
    else:
        assert found == originals


def test_hardlink_discarded_is_idempotent(invoke, make_box):
    """A second run finds the copies already sharing a file and leaves them be."""
    box_path, box_type, _ = make_box(Maildir, FULL_BOX)
    args = ("--strategy=select-one", "--action=hardlink-discarded", box_path)

    assert invoke(*args).exit_code == 0
    linked = {path: path.stat().st_ino for path in mail_files(box_path)}

    result = invoke(*args)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    assert "already shares the file of the copy kept" in result.stderr
    assert {path: path.stat().st_ino for path in mail_files(box_path)} == linked
    check_box(box_path, box_type, content=FULL_BOX)


def test_hardlink_that_cannot_be_created_leaves_the_mail(invoke, make_box, monkeypatch):
    """A link that cannot replace its mail leaves the mail as it was, removes the
    temporary link it went through, and counts the mail as skipped.
    """
    box_path, box_type, _ = make_box(Maildir, FULL_BOX)
    before = {path: path.stat().st_ino for path in mail_files(box_path)}
    replace = os.replace

    def refuse(src, dst):
        if Path(box_path) in Path(dst).parents:
            raise PermissionError(13, "Permission denied", dst)
        replace(src, dst)

    monkeypatch.setattr(os, "replace", refuse)

    result = invoke("--strategy=select-one", "--action=hardlink-discarded", box_path)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    assert (
        "2 mails left untouched: the link could not be created (Permission denied)."
        in result.stderr
    )
    assert {path: path.stat().st_ino for path in mail_files(box_path)} == before
    assert list(Path(box_path).rglob(f"{LINK_TEMP_PREFIX}*")) == []
    check_box(box_path, box_type, content=FULL_BOX)


def test_hardlink_discarded_leaves_file_based_box_alone(invoke, make_box):
    """A mail packed into the box's own file has nothing of its own to link, so the
    box comes out byte for byte as it went in.
    """
    box_path, box_type, _ = make_box(mbox, FULL_BOX)
    before = Path(box_path).read_bytes()

    result = invoke("--strategy=select-one", "--action=hardlink-discarded", box_path)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr
    assert "have no file of their own to link" in result.stderr
    assert Path(box_path).read_bytes() == before
    check_box(box_path, box_type, content=FULL_BOX)


@pytest.mark.parametrize("export_format", BoxFormat, ids=str)
@pytest.mark.parametrize("action", ("copy-selected", "move-selected"))
@pytest.mark.parametrize(
    "raw",
    (
        PARTLESS_HEADERS + "Taipei: 晴天, 28 °C.\r\nTainan: 多雲.\r\n".encode(),
        PARTLESS_HEADERS + b"Sunny.\r\n--Kiwi-Boundary--\r\nRain.\r\n",
    ),
    ids=("8bit", "closed"),
)
def test_export_keeps_partless_multipart(invoke, tmp_path, raw, action, export_format):
    """A multipart mail parsed with no subpart reaches every export format byte for
    byte, whether its body holds 8-bit bytes or a closing boundary.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/1090
    """
    # A folder of `.eml` files keeps the CRLF line endings of the mail on every
    # platform. On Windows, the stdlib boxes write each LF as CRLF, which doubles
    # the CR of a CRLF ending and ends the headers after the first one.
    source_path = tmp_path / "source"
    EML(str(source_path)).add(raw)
    export_path = tmp_path / "export"

    result = invoke(
        "--strategy=select-one",
        f"--action={action}",
        f"--export={export_path}",
        f"--export-format={export_format}",
        str(source_path),
    )

    assert result.exit_code == 0
    export = export_format.base_class(export_path, create=False)
    (key,) = export.keys()
    # The headers and the body are written with the line endings of the platform.
    assert export.get_bytes(key).replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n")


def test_unique_only_source_is_exported(invoke, make_box):
    """A source made only of unique mails still exports all of them: a set of one mail
    is auto-selected, not skipped as "all mails were selected".

    See: https://github.com/kdeldycke/mail-deduplicate/issues/843 and
    https://github.com/kdeldycke/mail-deduplicate/issues/599
    """
    uniques = [
        MailFactory(message_id=f"<uniq-{i}@nohost.com>", body=f"Body {i}\n")
        for i in range(3)
    ]
    box_path, _, export_path = make_box(Maildir, uniques)

    result = invoke(
        "--strategy=select-one",
        "--action=copy-selected",
        f"--export={export_path}",
        box_path,
    )

    assert result.exit_code == 0
    # All three unique mails were copied to the export box, none skipped.
    check_box(export_path, mbox, content=uniques)
