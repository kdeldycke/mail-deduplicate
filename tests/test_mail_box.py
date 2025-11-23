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
from mailbox import Mailbox, Message

import pytest

from mail_deduplicate.mail_box import (
    FILE_FORMATS,
    FOLDER_FORMATS,
    BoxFormat,
    BoxStructure,
)

from .conftest import MailFactory, check_box


@cache
def stdlib_box_types() -> list[type[Mailbox]]:
    """Yields all mailbox types defined in the standard library.

    Only collect direct subclasses of the ``mailbox.Mailbox`` interface. Ignore
    ``mailbox.Mailbox`` itself and all others starting with an underscore.
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
        assert box.base_class in stdlib_box_types()

        assert box.base_class.__name__.upper() == box.name
        assert str(box) == box.name.lower()

        assert box.structure in BoxStructure

        assert issubclass(box.message_class, Message)

    # Check all standard library box types are covered.
    assert set(stdlib_box_types()) == {box.base_class for box in BoxFormat}

    assert set(FOLDER_FORMATS).isdisjoint(FILE_FORMATS)
    assert set(BoxFormat) == set(FOLDER_FORMATS) | set(FILE_FORMATS)




@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_create_box(make_box, box_type):
    """Test creating a box with mails."""
    mail1 = MailFactory(body="First mail\n")
    mail2 = MailFactory(body="Second mail\n", message_id="<msg2@test.com>")

    box_path, created_type = make_box(box_type, [mail1, mail2])

    assert created_type == box_type
    check_box(box_path, box_type, [mail1, mail2])


@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_create_empty_box(make_box, box_type):
    """Test creating an empty box."""
    box_path, created_type = make_box(box_type)

    assert created_type == box_type
    check_box(box_path, box_type, [])


@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_box_with_duplicate_mails(make_box, box_type):
    """Test box containing duplicate mails."""
    mail1 = MailFactory(body="Duplicate content\n", message_id="<dup@test.com>")
    mail2 = MailFactory(body="Duplicate content\n", message_id="<dup@test.com>")
    mail3 = MailFactory(body="Unique mail\n", message_id="<unique@test.com>")

    box_path, created_type = make_box(box_type, [mail1, mail2, mail3])

    assert created_type == box_type
    check_box(box_path, box_type, [mail1, mail2, mail3])


@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_box_with_different_dates(make_box, box_type):
    """Test box with mails having different dates."""
    mail1 = MailFactory(date="2023-01-01", message_id="<jan@test.com>")
    mail2 = MailFactory(date="2023-06-15", message_id="<jun@test.com>")
    mail3 = MailFactory(date="2023-12-31", message_id="<dec@test.com>")

    box_path, created_type = make_box(box_type, [mail1, mail2, mail3])

    assert created_type == box_type
    check_box(box_path, created_type, [mail1, mail2, mail3])


@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_box_with_single_mail(make_box, box_type):
    """Test boxes with a single mail."""
    mail = MailFactory(body="Single mail\n")

    box_path, created_type = make_box(box_type, [mail])

    assert created_type == box_type
    check_box(box_path, box_type, [mail])


@pytest.mark.parametrize("box_type", [mailbox.Maildir, mailbox.mbox])
def test_box_types_from_fixture(make_box, box_type):
    """Test that make_box fixture works with different box types."""
    mails = [
        MailFactory(body="Mail 1\n", message_id="<1@test.com>"),
        MailFactory(body="Mail 2\n", message_id="<2@test.com>"),
        MailFactory(body="Mail 3\n", message_id="<3@test.com>"),
    ]

    box_path, created_type = make_box(box_type, mails)

    assert created_type == box_type
    check_box(box_path, box_type, mails)


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
    assert "Missing sub-directory" in str(result.exc_info[1])
