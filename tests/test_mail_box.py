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
from functools import cache
from mailbox import Mailbox, Message, NoSuchMailboxError, mbox
from pathlib import Path

import pytest

from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import (
    EML,
    FILE_FORMATS,
    FOLDER_FORMATS,
    BoxFormat,
    BoxStructure,
    create_box,
)

from .conftest import MailFactory, check_box


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


def test_box_format_definition():
    """Ensures all box formats are correctly defined."""
    for box in BoxFormat:
        assert issubclass(box.base_class, Mailbox)

        assert box.base_class.__name__.upper() == box.name
        assert str(box) == box.name.lower()

        assert box.structure in BoxStructure

        assert issubclass(box.message_class, Message)
        assert issubclass(box.message_class, DedupMailMixin)
        assert box.message_class.__name__.startswith(box.base_class.__name__)

        assert callable(box.constructor)

    # Check all standard library box types are covered, on top of which custom
    # formats like eml are provided.
    assert set(stdlib_box_types()) <= {box.base_class for box in BoxFormat}

    assert set(FOLDER_FORMATS).isdisjoint(FILE_FORMATS)
    assert set(BoxFormat) == set(FOLDER_FORMATS) | set(FILE_FORMATS)


# Sweep every BoxFormat, so format-agnostic behavior is checked over the whole set
# instead of the historical maildir/mbox pair.
ALL_FORMATS = pytest.mark.parametrize("box_format", tuple(BoxFormat), ids=str)


@ALL_FORMATS
def test_box_instantiation(make_box, box_format):
    """Each format opens through its own custom DedupMail factory."""
    box_type = box_format.base_class
    mail = MailFactory(body="Single mail\n")

    box_path, created_type, _ = make_box(box_type, [mail])

    assert created_type is box_type
    check_box(box_path, box_type, [mail])

    mail_box = box_format.constructor(box_path)
    assert isinstance(mail_box, box_format.base_class)
    assert issubclass(mail_box._factory, box_format.message_class)

    assert len(mail_box) == 1
    message = next(mail_box.itervalues())
    assert isinstance(message, box_format.message_class)
    assert isinstance(message, DedupMailMixin)
    assert hasattr(message, "source_path")
    assert hasattr(message, "mail_id")
    mail_box.close()


@ALL_FORMATS
def test_box_roundtrip(make_box, box_format):
    """A mix of unique and duplicate mails survives a build/read round-trip.

    Collapses several near-identical single-format round-trip tests into one sweep,
    and is the first time MH, Babyl and MMDF are exercised at all.
    """
    box_type = box_format.base_class
    mails = [
        MailFactory(body="First mail\n", message_id="<1@test.com>"),
        MailFactory(body="Second mail\n", message_id="<2@test.com>"),
        MailFactory(body="Duplicate content\n", message_id="<dup@test.com>"),
        MailFactory(body="Duplicate content\n", message_id="<dup@test.com>"),
    ]

    box_path, created_type, _ = make_box(box_type, mails)

    assert created_type is box_type
    check_box(box_path, box_type, mails)


@ALL_FORMATS
def test_box_empty(make_box, box_format):
    """An empty box of any format reads back as empty."""
    box_type = box_format.base_class
    box_path, created_type, _ = make_box(box_type)

    assert created_type is box_type
    check_box(box_path, box_type, [])


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


def test_force_unlock_recovers_stale_lock(invoke, make_box):
    """--force-unlock clears a stale lock that would otherwise abort the run."""
    dup = MailFactory(body="Same body.\n", message_id="<lock@test.com>")
    box_path, box_type, _ = make_box(mbox, [dup, dup])

    # Simulate a stale lock left behind by a crashed process.
    Path(box_path + ".lock").touch()

    # Without the flag, opening the locked box refuses to proceed and changes nothing.
    refused = invoke("--strategy=select-one", "--action=delete-discarded", box_path)
    assert refused.exit_code == 1
    assert "already locked" in refused.stderr.lower()
    check_box(box_path, box_type, content=[dup, dup])

    # With the flag, the stale lock is forced off and dedup runs to completion.
    forced = invoke(
        "--force-unlock",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )
    assert forced.exit_code == 0
    check_box(box_path, box_type, content=[dup])


def test_create_box_refuses_to_clobber_existing(tmp_path):
    """create_box refuses an existing path unless append is requested, guarding a
    destination box even when reached directly."""
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


def test_invalid_maildir_structure(invoke):
    result = invoke("--action=delete-discarded", ".")
    assert result.exit_code == 1
    assert "Step #1" in result.stdout
    assert "Opening " in result.stderr
    assert "Unrecognized folder" in str(result.exc_info[1])
    assert "--input-format" in str(result.exc_info[1])


def test_verbatim_nested_maildirs(invoke, tmp_path):
    """Nested plain-directory maildir folders (isync's Verbatim naming style) are
    discovered at any depth, without requiring the root to be a maildir itself.

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
    """Forcing the maildir format on a Verbatim-style tree does not crash on the
    mail-less root."""
    root = tmp_path / "backup"
    root.mkdir()
    box = mailbox.Maildir(str(root / "INBOX"), create=True)
    box.add(MailFactory().render())
    box.close()

    result = invoke("--input-format=maildir", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "1 mails found." in result.stderr


def test_mixed_maildir_folder_conventions(invoke, tmp_path):
    """Maildir++ dot-folders and Verbatim plain folders coexist under the same
    maildir root, each opened exactly once. Guards against subfolders being skipped
    so only the root INBOX is processed.

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
    """A folder of loose `.eml` files is autodetected and deduplicated, nested
    directories included.

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


def test_eml_forced_format(invoke, tmp_path):
    """The `eml` format can be forced on any folder."""
    root = tmp_path / "export"
    root.mkdir()
    (root / "one.eml").write_bytes(MailFactory().render())

    result = invoke("--input-format=eml", "--action=delete-discarded", str(root))

    assert result.exit_code == 0
    assert "1 mails found." in result.stderr


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
    assert [str(box.get_message(key)) for key in box.iterkeys()] == [
        str(dup_mail.as_message())
    ]


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
