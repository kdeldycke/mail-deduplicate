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
import signal
import subprocess
import sys
from contextlib import contextmanager
from email import message_from_bytes
from functools import cache
from mailbox import Mailbox, Message, NoSuchMailboxError

import pytest
from extra_platforms.pytest import skip_windows

from mail_deduplicate.action import Action
from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import (
    EML,
    FILE_FORMATS,
    FOLDER_FORMATS,
    PROFILE_LOCK,
    BoxFormat,
    BoxStructure,
    MailSourceError,
    autodetect_box_type,
    create_box,
    iter_mbox_files,
    lock_box,
)

from .conftest import ALL_FORMATS, MailFactory, assert_one_line_error, check_box

if sys.platform != "win32":
    import resource

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


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

    The next run needs no `--force-unlock`. A single-file box is left as the run
    found it, and a warning names it.
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
    result = invoke(*args)
    assert result.exit_code == 1
    # A single-file box only writes the removals it queued when it is closed, and a
    # run cut short leaves them unwritten. A folder-based box deletes each mail file
    # as soon as it is removed.
    queued = box_format.structure == BoxStructure.FILE
    check_box(box_path, box_type, content=[dup, dup] if queued else [dup])
    warning = f"The run stopped before it rewrote {box_path}:"
    assert (warning in result.stderr) is queued

    monkeypatch.undo()
    result = invoke(*args)
    assert result.exit_code == 0
    check_box(box_path, box_type, content=[dup])


STOP_POINT = "Removals queued, waiting to be stopped."
"""Line printed by `STOPPABLE_RUN` once its action has queued its removals.

The ID of the interpreter process follows it, on the same line.
"""


STOPPABLE_RUN = f"""
import os
import sys
import time

from mail_deduplicate.action import Action
from mail_deduplicate.cli import mdedup

perform = Action.perform


def perform_then_wait(self, dedup):
    perform(self, dedup)
    print({STOP_POINT!r}, os.getpid(), flush=True)
    time.sleep(60)


Action.perform = perform_then_wait
mdedup(sys.argv[1:])
"""
"""An `mdedup` run that waits to be stopped while it holds the locks of its boxes."""


@LOCKING_FORMATS
@pytest.mark.parametrize(
    "stop",
    [
        pytest.param(signal.SIGTERM, id="sigterm"),
        # Windows has no SIGKILL, and needs none: there, `os.kill()` ends a process
        # the same way whatever the signal.
        pytest.param(getattr(signal, "SIGKILL", signal.SIGTERM), id="sigkill"),
    ],
)
def test_killed_run_needs_force_unlock(invoke, make_box, box_format, stop):
    """A run stopped by `SIGTERM` or `SIGKILL` exits before any cleanup.

    Its box stays locked, and only `--force-unlock` lets the next run through.

    On Windows, `os.kill()` calls `TerminateProcess()` for any signal, which skips
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
            # Signal the interpreter, not the process started above. On Windows, the
            # `python` of a virtual environment is a launcher, which runs the
            # interpreter in a child process and exits after it, so the wait below
            # covers the interpreter. Stopped first, the launcher would leave the
            # interpreter to die later, still holding the box open.
            os.kill(int(line.split()[-1]), stop)
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
        pytest.param(
            ("--input-format=mbox",),
            ("Error: No mbox file found in ",),
            id="folder-without-mbox",
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


@pytest.mark.parametrize(
    ("content", "box_format"),
    (
        pytest.param(b"Subject: Plums\n\nRipe.\n", BoxFormat.EML, id="mail"),
        pytest.param(
            b"From plum@orchard.example Tue Nov 17 10:00:00 2026\n"
            b"Subject: Plums\n\nRipe.\n",
            BoxFormat.MBOX,
            id="mbox",
        ),
        pytest.param(b"", BoxFormat.MBOX, id="empty"),
        pytest.param(b"\x01\x01\x01\x01\nSubject: Plums\n", BoxFormat.MBOX, id="mmdf"),
        pytest.param(b"BABYL OPTIONS: -*- rmail -*-\n", BoxFormat.MBOX, id="babyl"),
    ),
)
def test_file_autodetect(tmp_path, content, box_format):
    """A file that starts with a header is one mail, and any other file an `mbox`."""
    path = tmp_path / "harvest"
    path.write_bytes(content)
    assert autodetect_box_type(path) is box_format


@pytest.mark.parametrize("autodetected", (True, False), ids=("autodetected", "forced"))
def test_source_without_mail_warns(invoke, tmp_path, autodetected):
    """A source in which no mail is found gets a warning.

    An autodetected file that is no mail is read as an `mbox`, so its warning names
    the formats that autodetection never finds. A forced format needs no such hint.
    """
    path = tmp_path / "empty.mbox"
    path.write_bytes(b"")
    args = () if autodetected else ("--input-format=mbox",)

    result = invoke(*args, "--hash-only", str(path))

    assert result.exit_code == 0
    assert f"No mail found in {path}." in result.stderr
    hint = "Name the format of a babyl or mmdf file with --input-format."
    assert (hint in result.stderr) is autodetected


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


@pytest.mark.parametrize("forced", (False, True), ids=("autodetected", "forced"))
def test_maildir_without_tmp_warns(invoke, tmp_path, forced):
    """A maildir folder that lost its empty `tmp` is skipped with a warning.

    `git` and other tools that skip empty folders leave a maildir this way. The
    warning names each such folder, at any depth, and the run still reads the
    complete maildir beside them.
    """
    root = tmp_path / "backup"
    for folder in ("INBOX", "Archive/2024", "Sent"):
        # `Maildir` creates its own folder, but not the folders above it.
        (root / folder).parent.mkdir(parents=True, exist_ok=True)
        box = mailbox.Maildir(str(root / folder), create=True)
        box.add(MailFactory().render())
        box.close()
    for folder in ("INBOX", "Archive/2024"):
        (root / folder / "tmp").rmdir()
    args = ("--input-format=maildir",) if forced else ()

    result = invoke(*args, "--hash-only", str(root))

    assert result.exit_code == 0
    for folder in ("INBOX", "Archive/2024"):
        assert (
            f"Skip {root / folder}: it holds a cur folder but no tmp folder."
            in result.stderr
        )
    assert result.stderr.count("1 mails found.") == 1
    assert "No mail found" not in result.stderr


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


def test_eml_single_mail_box(tmp_path):
    """An `eml` box opened on a file holds that one mail, under the file's name.

    Its accessors refuse any other key, even the name of a mail file beside it, and
    the box takes no other mail.
    """
    raw = MailFactory().render()
    path = tmp_path / "plums.txt"
    path.write_bytes(raw)
    (tmp_path / "pears.eml").write_bytes(raw)
    box = EML(str(path), create=False)

    assert list(box.iterkeys()) == ["plums.txt"]
    assert len(box) == 1
    assert "plums.txt" in box
    assert "pears.eml" not in box
    assert box.get_bytes("plums.txt") == raw
    for accessor in (box.get_file, box.get_bytes, box.remove):
        with pytest.raises(KeyError):
            accessor("pears.eml")
    with pytest.raises(NotADirectoryError):
        box.add(raw)


def test_single_mail_files_dedup(invoke, tmp_path):
    """Mail files given one by one are each a source of one mail, and deduplicated.

    The content of a file decides, not its name: a file that starts with a header is
    one mail. Deleting a mail deletes its file.
    """
    duplicate = MailFactory()
    files = {
        "one.eml": duplicate,
        "two.txt": duplicate,
        "three.eml": MailFactory(message_id="<unique@example.com>"),
    }
    for name, mail in files.items():
        (tmp_path / name).write_bytes(mail.render())

    result = invoke(
        "--strategy=select-one",
        "--action=delete-discarded",
        *(str(tmp_path / name) for name in files),
    )

    assert result.exit_code == 0
    assert result.stderr.count("eml detected.") == 3
    assert result.stderr.count("1 mails found.") == 3
    # `select-one` keeps the copy whose path sorts first.
    assert not (tmp_path / "two.txt").exists()
    assert (tmp_path / "one.eml").read_bytes() == duplicate.render()
    assert (tmp_path / "three.eml").is_file()


THUNDERBIRD_SUMMARY = '// <!-- <mdb:mork:z v="1.4"/> -->\n'
"""First line of the `.msf` summary Thunderbird keeps beside each folder."""

THUNDERBIRD_FILTERS = 'version="9"\nlogging="no"\n'
"""The `msgFilterRules.dat` file Thunderbird writes for an account with no filter."""


def build_thunderbird_tree(root: Path, folders: dict[str, list[MailFactory]]) -> None:
    """Lay out a tree of `mbox` folders as Thunderbird stores an account.

    `folders` maps the path of each folder file to its mails: the sub-folders of a
    folder are in its `<folder>.sbd` directory. Each folder gets an `.msf` summary
    beside it, and the account gets the file of its filters.
    """
    root.mkdir(parents=True)
    (root / "msgFilterRules.dat").write_text(THUNDERBIRD_FILTERS, encoding="UTF-8")
    for relative, mails in folders.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        box = mailbox.mbox(path, create=True)
        for mail in mails:
            box.add(mail.render())
        box.close()
        (root / f"{relative}.msf").write_text(THUNDERBIRD_SUMMARY, encoding="UTF-8")


def test_thunderbird_tree_autodetect_and_dedup(invoke, tmp_path):
    """A Thunderbird account is detected as a tree of `mbox` folders and deduplicated.

    The folders of `.sbd` directories are read too. The `.msf` summaries and the file
    of filters are not mails, and are left as they are.
    """
    root = tmp_path / "Mail" / "Local Folders"
    dup = MailFactory(date="2024-02-05", message_id="<dup@example.com>")
    unique = MailFactory(date="2024-02-06", message_id="<unique@example.com>")
    build_thunderbird_tree(
        root,
        {
            "Inbox": [dup, unique],
            # An empty folder is an empty file, recognized by its `.msf` summary.
            "Trash": [],
            "Inbox.sbd/Archive": [dup],
        },
    )

    result = invoke("--strategy=select-one", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "mbox detected." in result.stderr
    assert result.stderr.count("2 mails found.") == 1
    assert result.stderr.count("1 mails found.") == 1
    assert result.stderr.count("0 mails found.") == 1

    # One copy of the duplicated mail was deleted, its survivor and the unique mail
    # remain, and the files that are not folders were left untouched.
    total = 0
    for folder in ("Inbox", "Inbox.sbd/Archive"):
        box = mailbox.mbox(root / folder, create=False)
        total += len(box)
        box.close()
    assert total == 2
    assert b"<unique@example.com>" in (root / "Inbox").read_bytes()
    assert (root / "Inbox.msf").read_text(encoding="UTF-8") == THUNDERBIRD_SUMMARY
    filters = (root / "msgFilterRules.dat").read_text(encoding="UTF-8")
    assert filters == THUNDERBIRD_FILTERS


@pytest.mark.parametrize(
    "name",
    (
        pytest.param("Inbox~", id="backup"),
        pytest.param("#Inbox#", id="autosave"),
        pytest.param(".Inbox", id="hidden"),
        pytest.param("Inbox.mozmsgs/Inbox", id="search-support"),
    ),
)
def test_mbox_tree_skips_names_thunderbird_hides(tmp_path, name):
    """A copy of a folder is not read under a name Thunderbird never shows as a folder.

    Read, the copy would join a duplicate set with the folder it copies, and could be
    kept in place of the folder Thunderbird shows.
    """
    root = tmp_path / "Local Folders"
    build_thunderbird_tree(root, {"Inbox": [MailFactory()]})
    copy = root / name
    copy.parent.mkdir(exist_ok=True)
    copy.write_bytes((root / "Inbox").read_bytes())

    assert list(iter_mbox_files(root)) == [root / "Inbox"]


def test_mbox_tree_refused_lock_unlocks_the_folders_before_it(invoke, tmp_path):
    """A folder of the tree locked by another program stops the run.

    The folders locked before it are unlocked again: the next run needs no
    `--force-unlock`, and no `.lock` file stays in the tree, where Thunderbird would
    show it as a folder.
    """
    root = tmp_path / "Local Folders"
    build_thunderbird_tree(
        root,
        {
            "Inbox": [MailFactory(message_id="<apple@test.com>")],
            "Trash": [MailFactory(message_id="<kiwi@test.com>")],
        },
    )
    args = ("--strategy=select-one", "--action=delete-discarded", str(root))

    holder = mailbox.mbox(root / "Trash", create=False)
    holder.lock()
    try:
        refused = invoke(*args)
    finally:
        holder.unlock()
        holder.close()

    assert refused.exit_code == 1
    assert_one_line_error(refused, "Trash is already locked")
    assert not (root / "Inbox.lock").exists()
    assert invoke(*args).exit_code == 0


@skip_windows(reason="Windows has no `resource` module to lower the limit with.")
def test_mbox_tree_past_the_limit_of_open_files(invoke, tmp_path):
    """A tree of more folders than the limit of open files stops the run.

    Each `mbox` box keeps its file open until the end of the run. The error says how
    to get past the limit, and no `.lock` file stays in the tree.
    """
    root = tmp_path / "Local Folders"
    folders = 64
    build_thunderbird_tree(
        root,
        {
            f"Folder{index:02d}": [MailFactory(message_id=f"<folder-{index}@test.com>")]
            for index in range(folders)
        },
    )
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    # Room for the files this process holds already, but not for every box.
    lowered = len(os.listdir("/dev/fd")) + folders // 2
    resource.setrlimit(resource.RLIMIT_NOFILE, (lowered, hard))
    try:
        result = invoke("--hash-only", str(root))
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    assert result.exit_code == 1
    assert_one_line_error(result, "too many open files", "ulimit -n")
    assert not list(root.glob("*.lock"))


HOLD_PROFILE_LOCK = """\
import sys

lock = sys.argv[1]
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    # Read and write access, OPEN_EXISTING, and no sharing, as Thunderbird opens it.
    handle = kernel32.CreateFileW(lock, 0xC0000000, 0, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
else:
    import fcntl
    import os

    fcntl.lockf(os.open(lock, os.O_WRONLY), fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.read()
"""
"""Holds the lock of a profile the way a running Thunderbird does, until killed.

A lock of the test process itself would not do: `fcntl` locks never conflict within
one process.
"""


@contextmanager
def thunderbird_running(profile: Path) -> Generator[None, None, None]:
    """Hold the lock of *profile* from another process, as a running Thunderbird."""
    with subprocess.Popen(
        (sys.executable, "-c", HOLD_PROFILE_LOCK, str(profile / PROFILE_LOCK)),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="UTF-8",
    ) as holder:
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline() == "held\n"
            yield
        finally:
            holder.kill()


def build_thunderbird_profile(tmp_path: Path) -> tuple[Path, Path]:
    """A Thunderbird profile with its lock file, and an account holding a duplicate.

    Returns the profile and the `Local Folders` account in it.
    """
    profile = tmp_path / "kiwi.default-release"
    root = profile / "Mail" / "Local Folders"
    dup = MailFactory(message_id="<plum@test.com>")
    build_thunderbird_tree(root, {"Inbox": [dup, dup]})
    (profile / PROFILE_LOCK).touch()
    return profile.resolve(), root


@pytest.mark.parametrize(
    "args",
    (
        pytest.param(("--action=delete-discarded",), id="delete"),
        pytest.param(("--action=move-discarded", "--export={export}"), id="move"),
    ),
)
def test_thunderbird_open_refuses_to_remove_mails(invoke, tmp_path, args):
    """A run that deletes or moves mails refuses a profile Thunderbird has open.

    No mail is touched.
    """
    profile, root = build_thunderbird_profile(tmp_path)
    inbox = (root / "Inbox").read_bytes()
    args = [arg.format(export=tmp_path / "out.mbox") for arg in args]

    with thunderbird_running(profile):
        result = invoke("--strategy=select-one", *args, str(root))

    assert result.exit_code == 1
    assert_one_line_error(
        result,
        f"Thunderbird has the profile at {profile} open.",
        "Quit it before you delete or move the mails of",
    )
    assert (root / "Inbox").read_bytes() == inbox


@pytest.mark.parametrize(
    "args",
    (
        pytest.param(("--action=copy-selected", "--export={export}"), id="copy"),
        pytest.param(("--action=delete-discarded", "--dry-run"), id="dry-run"),
        pytest.param(("--action=delete-discarded", "--hash-only"), id="hash-only"),
    ),
)
def test_thunderbird_open_allows_runs_that_remove_no_mail(invoke, tmp_path, args):
    """A run that leaves the boxes as they are goes on while Thunderbird runs."""
    profile, root = build_thunderbird_profile(tmp_path)
    inbox = (root / "Inbox").read_bytes()
    args = [arg.format(export=tmp_path / "out.mbox") for arg in args]

    with thunderbird_running(profile):
        result = invoke("--strategy=select-one", *args, str(root))

    assert result.exit_code == 0
    assert (root / "Inbox").read_bytes() == inbox


@pytest.mark.parametrize("read_only", (False, True), ids=("writable", "read-only"))
def test_thunderbird_closed_lets_the_run_remove_mails(invoke, tmp_path, read_only):
    """The lock file Thunderbird leaves in its profile after it quits stops nothing.

    A lock file that cannot be tried, here a read-only one, counts as free too.
    """
    profile, root = build_thunderbird_profile(tmp_path)
    if read_only:
        (profile / PROFILE_LOCK).chmod(0o444)

    result = invoke("--strategy=select-one", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    box = mailbox.mbox(root / "Inbox", create=False)
    assert len(box) == 1
    box.close()


def test_thunderbird_forced_mbox_format(invoke, tmp_path):
    """The `mbox` format can be forced on a directory of mbox files."""
    root = tmp_path / "Local Folders"
    build_thunderbird_tree(root, {"Inbox": [MailFactory()]})

    result = invoke("--input-format=mbox", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "1 mails found." in result.stderr


def build_thunderbird_maildir_tree(
    root: Path, folders: dict[str, list[MailFactory]]
) -> None:
    """Lay out an account that Thunderbird stores as one file per message.

    `folders` maps the path of each folder to its mails: the sub-folders of a folder
    are in its `<folder>.sbd` directory. Each folder is a maildir with the `cur` and
    `tmp` directories Thunderbird creates, and no `new`. Its mails are in `cur`, under
    names of the form Thunderbird gives them. Each folder gets an `.msf` summary
    beside it, and the account gets the file of its filters.
    """
    root.mkdir(parents=True)
    (root / "msgFilterRules.dat").write_text(THUNDERBIRD_FILTERS, encoding="UTF-8")
    for relative, mails in folders.items():
        folder = root / relative
        (folder / "tmp").mkdir(parents=True)
        (folder / "cur").mkdir()
        for count, mail in enumerate(mails, start=1):
            name = f"1700000000.M{count}P4242Q{count}.kiwi"
            (folder / "cur" / name).write_bytes(mail.render())
        (root / f"{relative}.msf").write_text(THUNDERBIRD_SUMMARY, encoding="UTF-8")


def test_thunderbird_maildir_tree_autodetect_and_dedup(invoke, tmp_path):
    """An account of one file per message is read as maildir boxes, with no `new`.

    The folders of `.sbd` directories are read too. A run that deletes mails says to
    repair the changed folders in Thunderbird, which does not re-read them.
    """
    root = tmp_path / "Mail" / "Local Folders"
    dup = MailFactory(date="2024-02-05", message_id="<dup@example.com>")
    unique = MailFactory(date="2024-02-06", message_id="<unique@example.com>")
    build_thunderbird_maildir_tree(
        root,
        {
            "Inbox": [dup, unique],
            "Trash": [],
            "Inbox.sbd/Archive": [dup],
        },
    )

    result = invoke("--strategy=select-one", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "maildir detected." in result.stderr
    assert result.stderr.count("2 mails found.") == 1
    assert result.stderr.count("1 mails found.") == 1
    assert result.stderr.count("0 mails found.") == 1
    assert "Repair Folder" in result.stderr
    # One copy of the duplicated mail was deleted, and no folder gained a `new`.
    assert len(list(root.glob("**/cur/*"))) == 2
    assert not list(root.glob("**/new"))


@pytest.mark.parametrize(
    ("args", "repair"),
    (
        pytest.param(("--action=delete-discarded",), True, id="delete"),
        pytest.param(("--action=delete-discarded", "--dry-run"), False, id="dry-run"),
        pytest.param(("--action=copy-selected", "--export={export}"), False, id="copy"),
    ),
)
def test_thunderbird_maildir_folder_forced_format(invoke, tmp_path, args, repair):
    """The `maildir` format can be forced on a single folder of one file per message.

    Only a run that removes mails says to repair the folder.
    """
    root = tmp_path / "Local Folders"
    build_thunderbird_maildir_tree(root, {"Inbox": [MailFactory(), MailFactory()]})
    args = [arg.format(export=tmp_path / "out.mbox") for arg in args]

    result = invoke(
        "--input-format=maildir", "--strategy=select-one", *args, str(root / "Inbox")
    )

    assert result.exit_code == 0
    assert "2 mails found." in result.stderr
    assert ("Repair Folder" in result.stderr) is repair
