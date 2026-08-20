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
import re
import string
from email.utils import formatdate as maildate
from functools import partial
from mailbox import MH, MMDF, Babyl, Mailbox, Maildir, Message, mbox
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest
from boltons.iterutils import same
from click_extra.pytest import runner  # noqa: F401
from whenever import Date, Instant, Time

from mail_deduplicate.action import Action
from mail_deduplicate.cli import (
    DEFAULT_HASH_HEADERS,
    DEFAULT_MINIMAL_HEADERS,
    Config,
    mdedup,
)
from mail_deduplicate.deduplicate import BodyHasher
from mail_deduplicate.mail import TimeSource
from mail_deduplicate.mail_box import EML, BoxFormat

""" Fixtures, configuration and helpers for tests. """


BOX_TYPES = (Maildir, mbox, MH, Babyl, MMDF, EML)
"""All box classes the `make_box`/`check_box` helpers know how to build and read.

Covers every format in `BoxFormat`, so tests can parametrize over the whole set.
"""


DEDUP_ARGS = ("--strategy=select-newest", "--action=delete-discarded", "--dry-run")
"""A run that exercises every step without touching the mails on disk."""


@pytest.fixture()
def invoke(runner):  # noqa: F811
    return partial(runner.invoke, mdedup)


@pytest.fixture()
def config() -> Config:
    """A fully-populated `Config` carrying the CLI defaults.

    Lets unit tests instantiate `Deduplicate` and friends without going through the
    Click command. Mutate the returned mapping to exercise a specific setting.
    """
    return Config(
        input_format=None,
        force_unlock=False,
        hash_headers=DEFAULT_HASH_HEADERS,
        minimal_headers=DEFAULT_MINIMAL_HEADERS,
        hash_body=BodyHasher.SKIP,
        hash_only=False,
        cache=False,
        cache_path=None,
        size_threshold=512,
        content_threshold=768,
        show_diff=False,
        strategies=(),
        time_source=TimeSource.DATE_HEADER,
        regexp=None,
        action=Action.COPY_SELECTED,
        export=None,
        export_format=BoxFormat.MBOX,
        export_append=False,
        hardlink_differing=False,
        dry_run=False,
    )


class MailFactory:
    """Create fake mail messages to serve as unittest fixtures.

    Help production of either random, customized or deterministic mail message.
    """

    def __init__(self, **custom_fields) -> None:
        """Init the mail with custom fields.

        You can bypass data normalization by passing the pre-formatted date string with
        `date_rfc2822` custom field instead of `date`.
        """
        # Defaults fields values.
        self.fields = {
            "body": "Да, они летят.\n",
            "date": Instant.now(),
            "date_rfc2822": None,
            "message_id": "<201111231111.abcdef101@mail.nohost.com>",
        }

        # Check all custom fields are recognized and supported.
        assert set(custom_fields).issubset(self.fields)

        # Normalize the date to a whenever Instant. ISO date strings are anchored at
        # midnight UTC; whenever instances are passed through untouched.
        if "date" in custom_fields:
            date = custom_fields["date"]
            if isinstance(date, str):
                date = Date.parse_iso(date).at(Time.MIDNIGHT).assume_utc()
            custom_fields["date"] = date

        # Update default values with custom ones.
        self.fields.update(custom_fields)

        # Derive RFC-2822 date from the Instant if not set.
        if not self.fields.get("date_rfc2822"):
            assert isinstance(self.fields["date"], Instant)
            self.fields["date_rfc2822"] = maildate(self.fields["date"].timestamp())

    def render(self):
        """Returns the full, rendered content of the mail."""
        return dedent(
            """\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: {date_rfc2822}
            Received: from [11.11.11.11] (hello=nope.com)
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
                **self.fields,
            ),
        ).encode("utf-8")

    def as_message(self):
        """Returns the mail as an instance of `mailbox.Message`."""
        return Message(self.render())

    @staticmethod
    def random_string(length):
        return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


@pytest.fixture()
def make_box(tmp_path):
    """A generic fixture to produce a temporary box of mails.

    The mail container can be created in any format supported by Python's standard
    library, plus the custom `eml` format, via the `box_type` parameter. Supported
    values are listed in `BOX_TYPES`.
    """

    def _make_box(box_type, mails=None):
        """Create a fake box and populate it with mails."""
        # Check parameters.
        assert box_type in BOX_TYPES
        assert issubclass(box_type, Mailbox)

        if not mails:
            mails = []
        assert same(map(type, mails), MailFactory)

        # Create the container under a random name and put all provided mails there.
        box = box_type(tmp_path.joinpath(uuid4().hex), create=True)
        box.lock()
        for fake_mail in mails:
            box.add(fake_mail.render())
        dest_box_path = tmp_path.joinpath(uuid4().hex)

        box.close()
        return box._path, box_type, str(dest_box_path)

    return _make_box


def metrics(output: str) -> dict[str, str]:
    """Extracts the name and value of every metric of a run's report tables."""
    parsed = {}
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split("│") if cell.strip()]
        if len(cells) >= 2 and re.fullmatch(r"\d+", cells[1]):
            parsed[cells[0]] = cells[1]
    return parsed


def mail_files(box_path: str) -> list[Path]:
    """Every mail file of a folder-based box, in a stable order.

    Dot-prefixed files are left out, as every folder-based format skips them when
    listing its mails: the temporary link the hardlinking action goes through is one
    of them.
    """
    return sorted(
        path
        for path in Path(box_path).rglob("*")
        if path.is_file() and not path.name.startswith(".")
    )


def check_box(box_path, box_type, content=None):
    """Check the content of a mail box, in any of the `BOX_TYPES` formats.

    Does not use `set()` types internally to avoid silent deduplication. Translates
    all mails provided to `mailbox.Message` instances to provide fair comparison in a
    normalized space.

    ```{todo}
    Use a `Counter` to count occurrences, instead of comparing sorted lists of the
    string rendering of each mail.
    ```
    """
    # Check provided parameters.
    assert isinstance(box_path, str)
    assert box_type in BOX_TYPES
    assert not isinstance(content, set)
    if content is None:
        content = []
    assert same(map(type, content), MailFactory)

    # Compares the content of the box.
    box = box_type(box_path, create=False)

    assert len(box) == len(content)
    mails_found = sorted([str(m) for m in box])
    assert sorted([str(m.as_message()) for m in content]) == mails_found
    box.close()
