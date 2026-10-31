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

import inspect
import mailbox
import os
import subprocess
import sys
from email import message_from_bytes
from functools import cache
from mailbox import Mailbox, Message, NoSuchMailboxError

import pytest

from mail_deduplicate.action import Action
from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import (
    EML,
    FILE_FORMATS,
    FOLDER_FORMATS,
    BoxFormat,
    BoxStructure,
    MailSourceError,
    create_box,
    lock_box,
)

from .conftest import ALL_FORMATS, MailFactory, assert_one_line_error, check_box


@cache
def stdlib_box_types() -> list[type[Mailbox]]:
    """Yields all mailbox types defined in the standard library.

    Only collect direct subclasses of the `mailbox.Mailbox` interface. Ignore
    `mailbox.Mailbox` itself and all others starting with an underscore.
    """
    klass_list = []
    for _, klass in inspect.getmembers(mailbox, inspect.isclass):
        if (
            klass != Mailbox
            and not klass.__name__.startswith("_")
            and issubclass(klass, Mailbox)
        ):
            klass_list.append(klass)
    return klass_list


LOCKING_FORMATS = pytest.mark.parametrize(
    "box_format",
    (BoxFormat.MBOX, BoxFormat.MH, BoxFormat.BABYL, BoxFormat.MMDF),
    ids=str,
)
"""Sweeps a test over the formats that lock their box: maildir and eml take no
lock."""


@ALL_FORMATS
def test_box_format_definition(box_format):
    """Ensures each box format is correctly defined."""
    assert issubclass(box_format.base_class, Mailbox)

    assert box_format.base_class.__name__.upper() == box_format.name
    assert str(box_format) == box_format.name.lower()

    assert box_format.structure in BoxStructure

    assert issubclass(box_format.message_class, Message)
    assert issubclass(box_format.message_class, DedupMailMixin)
    assert box_format.message_class.__name__.startswith(box_format.base_class.__name__)

    assert callable(box_format.constructor)


def test_box_formats_cover_stdlib():
    """Box formats cover every box type of the standard library, plus custom ones.

    Custom formats like eml come on top, and each format has one structure.
    """
    assert set(stdlib_box_types()) <= {box.base_class for box in BoxFormat}

    assert set(FOLDER_FORMATS).isdisjoint(FILE_FORMATS)
    assert set(BoxFormat) == set(FOLDER_FORMATS) | set(FILE_FORMATS)


@ALL_FORMATS
@pytest.mark.parametrize(
    "mails",
    (
        pytest.param([], id="empty"),
        pytest.param([MailFactory(body="Single mail\n")], id="single"),
        pytest.param(
            [
                MailFactory(body="First mail\n", message_id="<1@test.com>"),
                MailFactory(body="Second mail\n", message_id="<2@test.com>"),
                MailFactory(body="Duplicate content\n", message_id="<dup@test.com>"),
                MailFactory(body="Duplicate content\n", message_id="<dup@test.com>"),
            ],
            id="mixed",
        ),
    ),
)
def test_box_roundtrip(make_box, box_format, mails):
    """Mails survive a build/read round-trip in each format.

    Each format opens through its own custom DedupMail factory.

    The duplicates of the mixed box check that no layer collapses identical mails.
    """
    box_type = box_format.base_class
    box_path, created_type, _ = make_box(box_type, mails)

    assert created_type is box_type
    check_box(box_path, box_type, mails)

    mail_box = box_format.constructor(box_path)
    assert isinstance(mail_box, box_format.base_class)
    assert issubclass(mail_box._factory, box_format.message_class)

    assert len(mail_box) == len(mails)
    for message in mail_box.itervalues():
        assert isinstance(message, box_format.message_class)
        assert isinstance(message, DedupMailMixin)
        assert hasattr(message, "source_path")
        assert hasattr(message, "mail_id")
    mail_box.close()


@ALL_FORMATS
def test_dedup_across_formats(invoke, make_box, box_format):
    """A full dedup run succeeds on every supported format.

    MH, Babyl and MMDF are never autodetected, so the format is forced. Babyl also
    guards a regression: its `get_file()` hands back a nameless in-memory buffer,
    which used to crash the extraction of a mail's path metadata.
    """
    box_type = box_format.base_class
    dup = MailFactory(body="Same body.\n", message_id="<dup@test.com>")
    unique = MailFactory(body="Unique body.\n", message_id="<unique@test.com>")

    box_path, _, _ = make_box(box_type, [dup, dup, unique])

    result = invoke(
        f"--input-format={box_format}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    # One copy of the duplicate is discarded; its survivor and the unique mail remain.
    check_box(box_path, box_type, content=[dup, unique])


@ALL_FORMATS
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_run_cut_short_unlocks_boxes(invoke, make_box, monkeypatch, box_format, error):
    """A run cut short by an error or an interrupt still unlocks its source box.

    The next run needs no `--force-unlock`.
    """
    box_type = box_format.base_class
    dup = MailFactory(body="Same body.\n", message_id="<cut-short@test.com>")
    box_path, _, _ = make_box(box_type, [dup, dup])
    args = (
        f"--input-format={box_format}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    # Fail once the action has queued its removals, before the boxes are closed.
    perform = Action.perform

    def perform_then_fail(self, dedup):
        perform(self, dedup)
        raise error

    monkeypatch.setattr(Action, "perform", perform_then_fail)
    assert invoke(*args).exit_code == 1
    # A single-file box only writes the removals it queued when it is closed, and a
    # run cut short leaves them unwritten. A folder-based box deletes each mail file
    # as soon as it is removed.
    queued = box_format.structure == BoxStructure.FILE
    check_box(box_path, box_type, content=[dup, dup] if queued else [dup])

    monkeypatch.undo()
    result = invoke(*args)
    assert result.exit_code == 0
    check_box(box_path, box_type, content=[dup])


STOP_POINT = "Removals queued, waiting to be stopped."
"""Line printed by `STOPPABLE_RUN` once its action has queued its removals."""


STOPPABLE_RUN = f"""
import sys
import time

from mail_deduplicate.action import Action
from mail_deduplicate.cli import mdedup

perform = Action.perform


def perform_then_wait(self, dedup):
    perform(self, dedup)
    print({STOP_POINT!r}, flush=True)
    time.sleep(60)


Action.perform = perform_then_wait
mdedup(sys.argv[1:])
"""
"""An `mdedup` run that waits to be stopped while it holds the locks of its boxes."""


@LOCKING_FORMATS
@pytest.mark.parametrize(
    "stop",
    [
        pytest.param(subprocess.Popen.terminate, id="sigterm"),
        pytest.param(subprocess.Popen.kill, id="sigkill"),
    ],
)
def test_killed_run_needs_force_unlock(invoke, make_box, box_format, stop):
    """A run stopped by `SIGTERM` or `SIGKILL` exits before any cleanup.

    Its box stays locked, and only `--force-unlock` lets the next run through.

    On Windows, `terminate()` and `kill()` both call `TerminateProcess()`, which skips
    the cleanup too.
    """
    box_type = box_format.base_class
    dup = MailFactory(body="Same body.\n", message_id="<killed@test.com>")
    box_path, _, _ = make_box(box_type, [dup, dup])
    args = (
        f"--input-format={box_format}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    with subprocess.Popen(
        (sys.executable, "-c", STOPPABLE_RUN, *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # The run prints characters that a legacy Windows code page cannot encode.
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        encoding="UTF-8",
    ) as process:
        try:
            assert process.stdout is not None
            output = ""
            for line in process.stdout:
                output += line
                if STOP_POINT in line:
                    break
            else:
                pytest.fail(f"The run ended before its action:\n{output}")
            stop(process)
            process.wait(timeout=30)
        finally:
            process.kill()
    assert process.returncode != 0

    # Nothing ran after the signal, so a single-file box keeps its queued removals
    # unwritten. A folder-based box deletes each mail file as soon as it is removed.
    queued = box_format.structure == BoxStructure.FILE
    left = [dup, dup] if queued else [dup]
    check_box(box_path, box_type, content=left)

    # Without the flag, the run refuses the locked box and changes nothing.
    refused = invoke(*args)
    assert refused.exit_code == 1
    assert "already locked" in refused.stderr.lower()
    check_box(box_path, box_type, content=left)

    forced = invoke("--force-unlock", *args)
    assert forced.exit_code == 0
    check_box(box_path, box_type, content=[dup])


@LOCKING_FORMATS
def test_refused_lock_keeps_no_file_open(make_box, box_format):
    """A box refused for an existing lock keeps no file open.

    `MH.lock()` opens `.mh_sequences` before it takes the lock, and `MH.close()` only
    closes that file for a locked box.
    """
    box_path, box_type, _ = make_box(box_format.base_class)
    holder = box_type(box_path)
    holder.lock()
    box = box_type(box_path)
    try:
        with pytest.raises(MailSourceError, match="already locked"):
            lock_box(box, force_unlock=False)
    finally:
        holder.unlock()
        holder.close()

    file = getattr(box, "_file", None)
    assert file is None or file.closed


def test_refused_subfolder_lock_unlocks_the_folders_before_it(invoke, make_box):
    """A subfolder locked by another program stops the run.

    The folders locked before it are unlocked again: the next run needs no
    `--force-unlock`.
    """
    box_path, _, _ = make_box(mailbox.MH, [MailFactory(message_id="<apple@test.com>")])
    root = mailbox.MH(box_path, create=False)
    root.add_folder("kiwi").add(MailFactory(message_id="<kiwi@test.com>").render())
    root.close()
    args = (
        "--input-format=mh",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    holder = mailbox.MH(os.path.join(box_path, "kiwi"), create=False)
    holder.lock()
    try:
        refused = invoke(*args)
    finally:
        holder.unlock()
        holder.close()

    assert refused.exit_code == 1
    assert_one_line_error(refused, "kiwi is already locked")
    assert invoke(*args).exit_code == 0


def test_create_box_refuses_to_clobber_existing(tmp_path):
    """create_box refuses an existing path unless append is requested.

    This guards a destination box even when reached directly.
    """
    existing = tmp_path / "existing.mbox"
    existing.touch()

    with pytest.raises(FileExistsError):
        create_box(existing, BoxFormat.MBOX, export_append=False)

    # With append, the existing box is opened instead of refused.
    box = create_box(existing, BoxFormat.MBOX, export_append=True)
    box.unlock()
    box.close()


@pytest.mark.parametrize("source", ["./dummy_maildir/", "./__init__.py"])
def test_nonexistent_path(invoke, source):
    result = invoke(source)
    assert result.exit_code == 2
    assert f"Path '{source}' does not exist" in result.stderr


@pytest.mark.parametrize(
    ("args", "messages"),
    (
        pytest.param(
            (),
            ("Error: Unrecognized folder", "--input-format"),
            id="unrecognized-folder",
        ),
        # A folder cannot be read as a single-file box.
        pytest.param(
            ("--input-format=mbox",), ("Error: Cannot read ",), id="folder-as-mbox"
        ),
    ),
)
def test_unusable_source(invoke, args, messages):
    """A source that cannot be opened in its format stops the run.

    No mail is touched.
    """
    result = invoke(*args, "--action=delete-discarded", ".")
    assert result.exit_code == 1
    assert "Step #1" in result.stdout
    assert "Opening " in result.stderr
    assert_one_line_error(result, *messages)


def test_verbatim_nested_maildirs(invoke, tmp_path):
    """Nested plain-directory maildir folders (isync's Verbatim style) are discovered.

    They are found at any depth, without requiring the root to be a maildir itself.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/973
    """
    root = tmp_path / "backup"
    dup_mail = MailFactory()
    unique_mail_1 = MailFactory(message_id="<unique-1@example.com>")
    unique_mail_2 = MailFactory(message_id="<unique-2@example.com>")

    (root / "Dev").mkdir(parents=True)
    layout = {
        "INBOX": [dup_mail, unique_mail_1],
        "Archive": [dup_mail],
        "Dev/GitHub": [unique_mail_2],
    }
    for folder, mails in layout.items():
        box = mailbox.Maildir(str(root / folder), create=True)
        for mail in mails:
            box.add(mail.render())
        box.close()

    result = invoke("--strategy=select-one", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "No mails at this level: only browse nested folders." in result.stderr

    # One copy of the duplicated mail was deleted, everything else is untouched.
    total = sum(
        len(mailbox.Maildir(str(root / folder), create=False)) for folder in layout
    )
    assert total == 3


def test_verbatim_forced_maildir_format(invoke, tmp_path):
    """Forcing maildir on a Verbatim-style tree does not crash on the mail-less root."""
    root = tmp_path / "backup"
    root.mkdir()
    box = mailbox.Maildir(str(root / "INBOX"), create=True)
    box.add(MailFactory().render())
    box.close()

    result = invoke("--input-format=maildir", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "1 mails found." in result.stderr


def test_mixed_maildir_folder_conventions(invoke, tmp_path):
    """Maildir++ dot-folders and Verbatim plain folders coexist under one root.

    Each opens exactly once. Guards against subfolders being skipped so only the root
    INBOX is processed.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/123
    """
    root = tmp_path / "backup"
    box = mailbox.Maildir(str(root), create=True)
    box.add(MailFactory(message_id="<root@example.com>").render())
    box.close()
    for folder in (".Old", "Sub"):
        sub_box = mailbox.Maildir(str(root / folder), create=True)
        sub_box.add(MailFactory(message_id=f"<{folder}@example.com>").render())
        sub_box.close()

    result = invoke("--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert result.stderr.count("1 mails found.") == 3


def test_eml_autodetect_and_dedup(invoke, tmp_path):
    """A folder of loose `.eml` files is autodetected and deduplicated.

    Nested directories are included.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/760
    """
    root = tmp_path / "export"
    (root / "2024").mkdir(parents=True)
    dup_mail = MailFactory()
    unique_mail = MailFactory(message_id="<unique@example.com>")

    (root / "one.eml").write_bytes(dup_mail.render())
    (root / "2024" / "two.eml").write_bytes(dup_mail.render())
    (root / "2024" / "three.EML").write_bytes(unique_mail.render())
    # Non-mail and hidden files are ignored.
    (root / "notes.txt").write_text("Not a mail.")
    (root / ".hidden.eml").write_bytes(dup_mail.render())

    result = invoke("--strategy=select-one", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "eml detected." in result.stderr
    assert "3 mails found." in result.stderr

    # One copy of the duplicated mail was deleted, everything else was preserved.
    box = EML(str(root), create=False)
    assert len(box) == 2
    assert (root / "notes.txt").is_file()
    assert (root / ".hidden.eml").is_file()


def test_eml_export_format(invoke, tmp_path):
    """Deduplicated mails can be exported as a folder of `.eml` files."""
    root = tmp_path / "export"
    root.mkdir()
    dup_mail = MailFactory()
    (root / "one.eml").write_bytes(dup_mail.render())
    (root / "two.eml").write_bytes(dup_mail.render())

    dest = tmp_path / "deduped"
    result = invoke(
        "--strategy=select-one",
        "--action=copy-selected",
        f"--export={dest}",
        "--export-format=eml",
        str(root),
    )

    assert result.exit_code == 0

    box = EML(str(dest), create=False)
    assert len(box) == 1
    assert [box.get_bytes(key) for key in box.iterkeys()] == [dup_mail.render()]


def test_eml_add_keeps_header_folding(tmp_path):
    """`EML.add()` writes a message with its headers folded as they were parsed.

    `Message.as_bytes()` refolds every header past 78 columns, where the stdlib boxes
    write them as they are.
    """
    raw = (
        b"Received: from mx.orchard.example by mail.orchard.example with ESMTPS id "
        b"abc123 for <quince@orchard.example>; Thu, 11 Oct 2018 09:30:01 +0800\n"
        b"Subject: Harvest\n"
        b"\n"
        b"Rain.\n"
    )
    box = EML(str(tmp_path / "box"))

    key = box.add(message_from_bytes(raw))

    assert box.get_bytes(key) == raw


def test_eml_nonexistent_box_raises(tmp_path):
    """Opening a missing `eml` folder without creating it fails cleanly."""
    with pytest.raises(NoSuchMailboxError):
        EML(str(tmp_path / "absent"), create=False)


def test_eml_membership(tmp_path):
    """`in` matches existing `.eml` keys only, and short-circuits on other names."""
    box = EML(str(tmp_path / "box"))
    key = box.add(MailFactory().render())

    assert key in box
    # A well-formed but absent key is not a member.
    assert "ghost.eml" not in box
    # A non-.eml name is rejected before any filesystem lookup.
    assert "notes.txt" not in box


def test_eml_missing_key_raises_keyerror(tmp_path):
    """Every accessor raises `KeyError` for an unknown key, like the stdlib boxes."""
    box = EML(str(tmp_path / "box"))
    for accessor in (box.get_file, box.get_bytes, box.remove):
        with pytest.raises(KeyError):
            accessor("ghost.eml")


def test_eml_folders_unsupported(tmp_path):
    """`eml` folders are walked recursively, so the subfolder API is inert."""
    box = EML(str(tmp_path / "box"))
    assert box.list_folders() == []
    with pytest.raises(NotImplementedError):
        box.get_folder("sub")
