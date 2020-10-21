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

from mailbox import Maildir
from string import ascii_lowercase

import arrow
import pytest

from ..strategy import (
    STRATEGY_METHODS,
    DISCARD_OLDER,
    DISCARD_OLDEST,
    DISCARD_NEWER,
    DISCARD_NEWEST,
    SELECT_OLDER,
    SELECT_OLDEST,
    SELECT_NEWER,
    SELECT_NEWEST,
    DISCARD_SMALLER,
    DISCARD_SMALLEST,
    DISCARD_BIGGER,
    DISCARD_BIGGEST,
    SELECT_SMALLER,
    SELECT_SMALLEST,
    SELECT_BIGGER,
    SELECT_BIGGEST,
    DISCARD_MATCHING_PATH,
    DISCARD_NON_MATCHING_PATH,
    SELECT_MATCHING_PATH,
    SELECT_NON_MATCHING_PATH,
    DISCARD_ONE,
    DISCARD_ALL_BUT_ONE,
    SELECT_ONE,
    SELECT_ALL_BUT_ONE,
)
from .conftest import MailFactory, check_box


def test_strategy_definitions():
    """ Test deduplication strategy definitions. """
    for strategy_id, method in STRATEGY_METHODS.items():
        # All strategies are lower cases strings, with dashes.
        assert isinstance(strategy_id, str)
        assert set(strategy_id).issubset(ascii_lowercase + "-")
        assert callable(method)


# Collections of pre-defined fixtures to use in the deduplication tests below.
smallest_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
smaller_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş. ++")
bigger_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++"
)
biggest_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++++++"
)


# List of strategies and their required dummy options.
strategy_options = dict.fromkeys(STRATEGY_METHODS, [])
# Add dummy regexps.
strategy_options.update(
    {
        "discard-matching-path": ["--regexp=.*"],
        "discard-non-matching-path": ["--regexp=.*"],
        "select-matching-path": ["--regexp=.*"],
        "select-non-matching-path": ["--regexp=.*"],
    }
)


@pytest.mark.parametrize("strategy_id,options", strategy_options.items())
def test_maildir_dry_run(invoke, make_box, strategy_id, options):
    """ Check no mail is removed in dry-run mode. """
    box_path, box_type = make_box(
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

    result = invoke(
        f"--strategy={strategy_id}",
        *options,
        "--action=delete-selected",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 0
    check_box(
        box_path,
        box_type,
        content=[
            smallest_mail,
            bigger_mail,
            smallest_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_SMALLER, DISCARD_BIGGEST])
def test_maildir_smaller_strategy(invoke, make_box, strategy_id):
    """ Test strategy of small mail selection. """
    box_path, box_type = make_box(
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

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Biggest mails are selected but not the smaller ones.
    check_box(
        box_path,
        box_type,
        content=[biggest_mail, biggest_mail],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_SMALLEST, DISCARD_BIGGER])
def test_maildir_smallest_strategy(invoke, make_box, strategy_id):
    """ Test strategy of smallest mail selection. """
    box_path, box_type = make_box(
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

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Bigger mails are selected but not the smallest ones.
    check_box(
        box_path,
        box_type,
        content=[
            biggest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_BIGGER, DISCARD_SMALLEST])
def test_maildir_bigger_strategy(invoke, make_box, strategy_id):
    """ Test strategy of bigger mail selection. """
    box_path, box_type = make_box(
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

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Smallest mails are selected but not the bigger ones.
    check_box(
        box_path,
        box_type,
        content=[smallest_mail, smallest_mail],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_BIGGEST, DISCARD_SMALLER])
def test_maildir_biggest_strategy(invoke, make_box, strategy_id):
    """ Test strategy of biggest mail selection. """
    box_path, box_type = make_box(
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

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Smaller mails are selected but not the biggest ones.
    check_box(
        box_path,
        box_type,
        content=[
            smallest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    )


newest_date = arrow.utcnow()
newer_date = newest_date.shift(minutes=-1)
older_date = newest_date.shift(minutes=-2)
oldest_date = newest_date.shift(minutes=-3)


newest_mail = MailFactory(date=newest_date)
newer_mail = MailFactory(date=newer_date)
older_mail = MailFactory(date=older_date)
oldest_mail = MailFactory(date=oldest_date)


@pytest.mark.parametrize("strategy_id", [SELECT_OLDER, DISCARD_NEWEST])
def test_maildir_older_strategy(invoke, make_box, strategy_id):
    """ Test strategy of older mail selection. """
    box_path, box_type = make_box(
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
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Newest mails are selected but not the older ones.
    check_box(
        box_path,
        box_type,
        content=[newest_mail, newest_mail],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_OLDEST, DISCARD_NEWER])
def test_maildir_oldest_strategy(invoke, make_box, strategy_id):
    """ Test strategy of oldest mail selection. """
    box_path, box_type = make_box(
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
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Newer mails are selected but not the oldest ones.
    check_box(
        box_path,
        box_type,
        content=[
            newest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
        ],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_NEWER, DISCARD_OLDEST])
def test_maildir_newer_strategy(invoke, make_box, strategy_id):
    """ Test strategy of newer mail selection. """
    box_path, box_type = make_box(
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
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Oldest mails are selected but not the newer ones.
    check_box(
        box_path,
        box_type,
        content=[oldest_mail, oldest_mail],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_NEWEST, DISCARD_OLDER])
def test_maildir_newest_strategy(invoke, make_box, strategy_id):
    """ Test strategy of newest mail selection. """
    box_path, box_type = make_box(
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
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Older mails are selected but not the newest ones.
    check_box(
        box_path,
        box_type,
        content=[
            oldest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
        ],
    )


random_mail_1 = MailFactory(message_id=MailFactory.random_string(30))
random_mail_2 = MailFactory(message_id=MailFactory.random_string(30))


@pytest.mark.parametrize("strategy_id", [SELECT_ONE, DISCARD_ALL_BUT_ONE])
def test_maildir_one_strategy(invoke, make_box, strategy_id):
    """ Test strategy of discarding one random duplicate. """
    box_path, box_type = make_box(
        Maildir,
        [
            random_mail_1,
            random_mail_1,
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_2,
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Newest mails are selected but not the older ones.
    check_box(
        box_path,
        box_type,
        content=[
            random_mail_1,
            random_mail_1,
            random_mail_2,
            random_mail_2,
        ],
    )


@pytest.mark.parametrize("strategy_id", [SELECT_ALL_BUT_ONE, DISCARD_ONE])
def test_maildir_all_but_one_strategy(invoke, make_box, strategy_id):
    """ Test strategy of discarding all but one random duplicate. """
    box_path, box_type = make_box(
        Maildir,
        [
            random_mail_1,
            random_mail_1,
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_2,
        ],
    )

    result = invoke(f"--strategy={strategy_id}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    # Newest mails are selected but not the older ones.
    check_box(
        box_path,
        box_type,
        content=[
            random_mail_1,
            random_mail_2,
        ],
    )
