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

import random
import string
from email.utils import formatdate as maildate
from functools import partial
from mailbox import Mailbox, Maildir, Message, mbox
from textwrap import dedent
from uuid import uuid4

import arrow
import pytest
from boltons.iterutils import same
from click_extra.tests.conftest import invoke as invoke_extra  # noqa: F401
from click_extra.tests.conftest import runner  # noqa: F401

from ..cli import mdedup

""" Fixtures, configuration and helpers for tests. """


@pytest.fixture
def invoke(invoke_extra):  # noqa: F811
    return partial(invoke_extra, mdedup)


class MailFactory:
    """Create fake mail messages to serve as unittest fixtures.

    Help production of either random, customized or deterministic mail message.
    """

    def __init__(self, **custom_fields):
        """Init the mail with custom fields.

        You can bypass data normalization by passing the pre-formated date string with
        ``date_rfc2822`` custom field instead of ``date``.
        """
        # Defaults fields values.
        self.fields = {
            "body": "Да, они летят.",
            "date": arrow.utcnow(),
            "date_rfc2822": None,
            "message_id": "<201111231111.abcdef101@mail.nohost.com>",
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
        """Returns the full, rendered content of the mail."""
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
            Message-Id: {message_id}
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

    @staticmethod
    def random_string(length):
        return "".join(random.choice(string.ascii_lowercase) for i in range(length))


@pytest.fixture
def make_box(tmp_path):
    """A generic fixture to produce a temporary box of mails.

    The mail container can be created in any format supported by Python standard
    library, by the way of the ``box_type`` parameter. Supported values: only
    ``Maildir`` and ``mbox`` for the moment.
    """

    def _make_box(box_type, mails=None):
        """Create a fake maildir and populate it with mails."""
        # Check parameters.
        assert box_type in (Maildir, mbox)
        assert issubclass(box_type, Mailbox)

        if not mails:
            mails = []
        assert same(map(type, mails), MailFactory)

        # Create the container under a random name and put all provided mails there.
        box = box_type(tmp_path.joinpath(uuid4().hex), create=True)
        box.lock()
        for fake_mail in mails:
            box.add(fake_mail.render())

        box.close()
        return box._path, box_type

    return _make_box


def check_box(box_path, box_type, content=None):
    """Check the content of a mail box (in any of maildir of mbox format).

    Does not use ``set()`` types internally to avoid silent deduplication. Translates
    all mails provided to ``mailbox.Message`` instances to provide fair comparison in a
    normalized space.
    """
    # Check provided parameters.
    assert isinstance(box_path, str)
    assert box_type in (Maildir, mbox)
    assert not isinstance(content, set)
    if content is None:
        content = []
    assert same(map(type, content), MailFactory)

    # Compares the content of the box.
    box = box_type(box_path, create=False)

    # TODO: use a Counter to count occurrences.

    assert len(box) == len(content)
    mails_found = sorted([str(m) for m in box])
    assert sorted([str(m.as_message()) for m in content]) == mails_found
    box.close()
