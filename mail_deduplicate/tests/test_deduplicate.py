# -*- coding: utf-8 -*-
#
# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
# All Rights Reserved.
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

from email.utils import formatdate as maildate
from textwrap import dedent
from uuid import uuid4

from mailbox import Mailbox, Message, Maildir, mbox
from pathlib import Path

import pytest
import arrow

from .. import STRATEGIES
from ..deduplicate import DuplicateSet


class MailFactory:

    """Create fake mail messages to serve as unittest fixtures.

    Help production of either random, customized or deterministic mail message.
    """

    def __init__(self, **custom_fields):
        """Init the mail with custom fields.

        You can bypass data normalization by passing the pre-formated date
        string with ``date_rfc2822`` custom field instead of ``date``.
        """
        # Defaults fields values.
        self.fields = {
            "body": "Да, они летят.",
            "date": arrow.utcnow(),
            "date_rfc2822": None,
        }

        # Check all custom fields are recognized and supported.
        assert set(custom_fields).issubset(self.fields)

        # Parse dates and normalize to Arrow instance.
        if "date" in custom_fields:
            custom_fields["date"] = arrow.get(custom_fields["date"])

        # Update default values with custom ones.
        self.fields.update(custom_fields)

        # Derive RFC-2822 date from arrow object if not set.
        if not self.fields.get("date_rfc2822"):
            self.fields["date_rfc2822"] = maildate(self.fields["date"].float_timestamp)

    def render(self):
        """ Returns the full, rendered content of the mail. """
        return dedent(
            """\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: {date_rfc2822}
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; {date_rfc2822}
            Date: {date_rfc2822}
            From: foo@bar.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: baz
            Subject: A duplicate mail
            Mime-Version: 1.0
            Content-Length: 60
            Content-Type: text/plain; charset="utf-8"
            Content-Transfer-Encoding: 8bit
            {body}""".format(
                **self.fields
            )
        ).encode("utf-8")

    def as_message(self):
        """Returns the mail as an instance of ``mailbox.Message``."""
        return Message(self.render())

    def save(self, filepath):
        """ Save the mail to the filesystem. """
        with open(filepath, "wb") as mail_file:
            mail_file.write(self.render())
        # TODO: find a way to set ctime here so we can test for time-based
        # deduplication strategies.


@pytest.fixture
def make_box(tmp_path):
    """A generic fixture to produce a temporary box of mails.

    The mail container can be created in any format supported by Python standard
    library, by the way of the ``box_type`` parameter. Supported values: only
    ``Maildir`` and ``mbox`` for the moment.
    """

    def _make_mailbox(box_type, mails):
        """Create a fake maildir and populate it with mails."""
        # Check parameters.
        assert box_type in (Maildir, mbox)
        assert issubclass(box_type, Mailbox)
        assert {isinstance(m, MailFactory) for m in mails} == {True}

        # Create the container under a random name and put all provided mails there.
        box = box_type(tmp_path.joinpath(uuid4().hex), create=True)
        box.lock()
        for fake_mail in mails:
            box.add(fake_mail.render())

        box.close()
        return box._path

    return _make_mailbox


def check_box(box_path, box_type, kept=None, deleted=None):
    """Check the content of a mail box (in any of maildir of mbox format).

    Does not use ``set()`` types internally to avoid silent deduplication.
    Translates all mails provided to ``mailbox.Message`` instances to provide
    fair comparison in a normalized space.
    """
    # Check provided parameters.
    assert isinstance(box_path, str)
    assert box_type in (Maildir, mbox)
    for mail_list in (kept, deleted):
        assert not isinstance(mail_list, set)
        if mail_list is None:
            mail_list = []
        if mail_list:
            assert {isinstance(m, MailFactory) for m in mail_list} == {True}

    # Compares the content of the box.
    box = box_type(box_path, create=False)
    assert len(box) == len(kept)
    mails_found = sorted([str(m) for m in box])
    assert sorted([str(m.as_message()) for m in kept]) == mails_found
    for mail in deleted:
        assert str(mail.as_message()) not in mails_found
    box.close()


# Collections of pre-defined fixtures to use in the deduplication tests below.
smallest_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
smaller_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş. ++")
bigger_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++"
)
biggest_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++++++"
)


def test_strategy_definitions():
    """ Test deduplication strategy definitions. """
    for strategy_id in STRATEGIES:
        method_id = strategy_id.replace("-", "_")
        assert hasattr(DuplicateSet, method_id)
        assert callable(getattr(DuplicateSet, method_id))


def test_maildir_smaller_strategy_dry_run(invoke, make_box):
    """ Check no mail is removed in dry-run mode. """
    box_path = make_box(
        Maildir,
        [
            smallest_mail,
            bigger_mail,
            smallest_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    )

    result = invoke("--strategy=delete-smaller", "--dry-run", box_path)

    assert result.exit_code == 0
    check_box(
        box_path,
        Maildir,
        kept=[
            smallest_mail,
            bigger_mail,
            smallest_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    )


def test_maildir_smaller_strategy(invoke, make_box):
    """ Test strategy of small mail deletion. """
    box_path = make_box(
        Maildir,
        [
            smallest_mail,
            biggest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )

    result = invoke("--strategy=delete-smaller", box_path)

    assert result.exit_code == 0
    # Biggest mails are kept but not the smaller ones.
    check_box(
        box_path,
        Maildir,
        kept=[biggest_mail, biggest_mail],
        deleted=[
            smallest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    )


def test_maildir_smallest_strategy(invoke, make_box):
    """ Test strategy of smallest mail deletion. """
    box_path = make_box(
        Maildir,
        [
            smallest_mail,
            biggest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )

    result = invoke("--strategy=delete-smallest", box_path)

    assert result.exit_code == 0
    # Bigger mails are kept but not the smallest ones.
    check_box(
        box_path,
        Maildir,
        kept=[
            biggest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
        deleted=[smallest_mail, smallest_mail],
    )


def test_maildir_bigger_strategy(invoke, make_box):
    """ Test strategy of bigger mail deletion. """
    box_path = make_box(
        Maildir,
        [
            smallest_mail,
            biggest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )

    result = invoke("--strategy=delete-bigger", box_path)

    assert result.exit_code == 0
    # Smallest mails are kept but not the bigger ones.
    check_box(
        box_path,
        Maildir,
        kept=[smallest_mail, smallest_mail],
        deleted=[
            biggest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )


def test_maildir_biggest_strategy(invoke, make_box):
    """ Test strategy of biggest mail deletion. """
    box_path = make_box(
        Maildir,
        [
            smallest_mail,
            biggest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )

    result = invoke("--strategy=delete-biggest", box_path)

    assert result.exit_code == 0
    # Smaller mails are kept but not the biggest ones.
    check_box(
        box_path,
        Maildir,
        kept=[
            smallest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
        deleted=[biggest_mail, biggest_mail],
    )


newest_date = arrow.utcnow()
newer_date = newest_date.shift(minutes=-1)
older_date = newest_date.shift(minutes=-2)
oldest_date = newest_date.shift(minutes=-3)


newest_mail = MailFactory(date=newest_date)
newer_mail = MailFactory(date=newer_date)
older_mail = MailFactory(date=older_date)
oldest_mail = MailFactory(date=oldest_date)
invalid_date_mail = MailFactory(date_rfc2822="Thu, 13 Dec 101 15:30 WET")


def test_maildir_older_strategy(invoke, make_box):
    """ Test strategy of older mail deletion. """
    box_path = make_box(
        Maildir,
        [
            oldest_mail,
            newest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
    )

    result = invoke("--time-source=date-header", "--strategy=delete-older", box_path)

    assert result.exit_code == 0
    # Newest mails are kept but not the older ones.
    check_box(
        box_path,
        Maildir,
        kept=[newest_mail, newest_mail],
        deleted=[
            oldest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            invalid_date_mail,
        ],
    )


def test_maildir_oldest_strategy(invoke, make_box):
    """ Test strategy of oldest mail deletion. """
    box_path = make_box(
        Maildir,
        [
            oldest_mail,
            newest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
    )

    result = invoke("--time-source=date-header", "--strategy=delete-oldest", box_path)

    assert result.exit_code == 0
    # Newer mails are kept but not the oldest ones.
    check_box(
        box_path,
        Maildir,
        kept=[
            newest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
        deleted=[oldest_mail, oldest_mail],
    )


def test_maildir_newer_strategy(invoke, make_box):
    """ Test strategy of newer mail deletion. """
    box_path = make_box(
        Maildir,
        [
            oldest_mail,
            newest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
    )

    result = invoke("--time-source=date-header", "--strategy=delete-newer", box_path)

    assert result.exit_code == 0
    # Oldest mails are kept but not the newer ones.
    check_box(
        box_path,
        Maildir,
        kept=[oldest_mail, oldest_mail],
        deleted=[
            newest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
    )


def test_maildir_newest_strategy(invoke, make_box):
    """ Test strategy of newest mail deletion. """
    box_path = make_box(
        Maildir,
        [
            oldest_mail,
            newest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
            invalid_date_mail,
        ],
    )

    result = invoke("--time-source=date-header", "--strategy=delete-newest", box_path)

    assert result.exit_code == 0
    # Older mails are kept but not the newest ones.
    check_box(
        box_path,
        Maildir,
        kept=[
            oldest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            invalid_date_mail,
        ],
        deleted=[newest_mail, newest_mail],
    )
