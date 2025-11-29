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

from mailbox import Maildir
from string import ascii_lowercase

import arrow
import pytest

from mail_deduplicate.strategy import Strategy

from .conftest import MailFactory, check_box


def test_strategy_definitions():
    """Test deduplication strategy definitions."""

    # Check there is no hidden aliases defined in the Strategy enum.
    assert len(Strategy) == len(Strategy.__members__)
    assert len(Strategy) == len(Strategy._value2member_map_)

    all_strategy_ids = {s.name.lower() for s in Strategy}

    for strategy in Strategy:
        assert isinstance(strategy.value, str | int)

        assert strategy.name.lower().replace("_", "-") == str(strategy)

        assert set(str(strategy)).issubset(ascii_lowercase + "-")
        assert callable(strategy.strategy_function)
        assert strategy.strategy_function.__name__ in all_strategy_ids
        assert strategy.strategy_function.__doc__.strip()


# Time-based collection of pre-defined fixtures.
now = arrow.utcnow()
newest_mail = MailFactory(date=now)
newer_mail = MailFactory(date=now.shift(minutes=-1))
older_mail = MailFactory(date=now.shift(minutes=-2))
oldest_mail = MailFactory(date=now.shift(minutes=-3))


# Size-based collection of pre-defined fixtures.
smallest_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
smaller_mail = MailFactory(body="Hello I am a duplicate mail. With annoying ćĥäŖş. ++")
bigger_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++",
)
biggest_mail = MailFactory(
    body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++++++",
)


# Quantity-based collection of pre-defined fixtures.
random_mail_1 = MailFactory(message_id=MailFactory.random_string(30))
random_mail_2 = MailFactory(message_id=MailFactory.random_string(30))
random_mail_3 = MailFactory(message_id=MailFactory.random_string(30))


# List of strategies and their required dummy parameters.
strategy_options: dict[str, list[str]] = dict.fromkeys(map(str, Strategy), [])
# Add dummy regexps.
strategy_options.update(
    {
        "discard-matching-path": ["--regexp=.*"],
        "discard-non-matching-path": ["--regexp=.*"],
        "select-matching-path": ["--regexp=.*"],
        "select-non-matching-path": ["--regexp=.*"],
    },
)


@pytest.mark.parametrize(("strategy_id", "params"), strategy_options.items())
def test_maildir_dry_run(invoke, make_box, strategy_id, params):
    """Check no mail is removed in dry-run mode."""
    box_path, box_type, _ = make_box(
        Maildir,
        [
            newest_mail,
            newest_mail,
            newer_mail,
            newer_mail,
            older_mail,
            older_mail,
            oldest_mail,
            oldest_mail,
            smallest_mail,
            smallest_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            bigger_mail,
            biggest_mail,
            biggest_mail,
            random_mail_1,
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_3,
            random_mail_3,
        ],
    )

    result = invoke(
        f"--strategy={strategy_id}",
        *params,
        "--action=delete-selected",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 0
    check_box(
        box_path,
        box_type,
        content=[
            newest_mail,
            newest_mail,
            newer_mail,
            newer_mail,
            older_mail,
            older_mail,
            oldest_mail,
            oldest_mail,
            smallest_mail,
            smallest_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            bigger_mail,
            biggest_mail,
            biggest_mail,
            random_mail_1,
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_3,
            random_mail_3,
        ],
    )


# List of (case_id, strategies, mailbox_input, mailbox_results).
test_cases = [
    # Whatever the time-based or size-based strategy, the duplicate set is not
    # actionable if the selection criterion doesn't produce any match.
    (
        "no_match",
        [
            Strategy.DISCARD_OLDER,
            Strategy.DISCARD_OLDEST,
            Strategy.DISCARD_NEWER,
            Strategy.DISCARD_NEWEST,
            Strategy.SELECT_OLDER,
            Strategy.SELECT_OLDEST,
            Strategy.SELECT_NEWER,
            Strategy.SELECT_NEWEST,
            Strategy.DISCARD_SMALLER,
            Strategy.DISCARD_SMALLEST,
            Strategy.DISCARD_BIGGER,
            Strategy.DISCARD_BIGGEST,
            Strategy.SELECT_SMALLER,
            Strategy.SELECT_SMALLEST,
            Strategy.SELECT_BIGGER,
            Strategy.SELECT_BIGGEST,
        ],
        [random_mail_1, random_mail_1],
        [random_mail_1, random_mail_1],
    ),
    (
        "older_selection",
        [Strategy.SELECT_OLDER, Strategy.DISCARD_NEWEST],
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
        # Newest mails are selected but not the older ones.
        [newest_mail, newest_mail],
    ),
    (
        "oldest_selection",
        [Strategy.SELECT_OLDEST, Strategy.DISCARD_NEWER],
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
        # Newer mails are selected but not the oldest ones.
        [
            newest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
            newest_mail,
        ],
    ),
    (
        "newer_selection",
        [Strategy.SELECT_NEWER, Strategy.DISCARD_OLDEST],
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
        # Oldest mails are selected but not the newer ones.
        [oldest_mail, oldest_mail],
    ),
    (
        "newest_selection",
        [Strategy.SELECT_NEWEST, Strategy.DISCARD_OLDER],
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
        # Older mails are selected but not the newest ones.
        [
            oldest_mail,
            oldest_mail,
            newer_mail,
            older_mail,
            older_mail,
            newer_mail,
        ],
    ),
    (
        "smaller_selection",
        [Strategy.SELECT_SMALLER, Strategy.DISCARD_BIGGEST],
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
        # Biggest mails are selected but not the smaller ones.
        [biggest_mail, biggest_mail],
    ),
    (
        "smallest_selection",
        [Strategy.SELECT_SMALLEST, Strategy.DISCARD_BIGGER],
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
        # Bigger mails are selected but not the smallest ones.
        [
            biggest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
            biggest_mail,
        ],
    ),
    (
        "bigger_selection",
        [Strategy.SELECT_BIGGER, Strategy.DISCARD_SMALLEST],
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
        # Smallest mails are selected but not the bigger ones.
        [smallest_mail, smallest_mail],
    ),
    (
        "biggest_selection",
        [Strategy.SELECT_BIGGEST, Strategy.DISCARD_SMALLER],
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
        # Smaller mails are selected but not the biggest ones.
        [
            smallest_mail,
            smallest_mail,
            bigger_mail,
            smaller_mail,
            smaller_mail,
            bigger_mail,
        ],
    ),
    (
        "one_selection",
        [Strategy.SELECT_ONE, Strategy.DISCARD_ALL_BUT_ONE],
        [
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_1,
            random_mail_3,
            random_mail_2,
        ],
        [
            random_mail_1,
            random_mail_2,
            random_mail_2,
        ],
    ),
    (
        "all_but_one_selection",
        [Strategy.SELECT_ALL_BUT_ONE, Strategy.DISCARD_ONE],
        [
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_1,
            random_mail_3,
            random_mail_2,
        ],
        [
            random_mail_1,
            random_mail_2,
        ],
    ),
]

select_test_cases = [
    # Whatever the time-based or size-based strategy, the duplicate set is not
    # actionable if the selection criterion doesn't produce any match.
    (
        "one_selection",
        [Strategy.SELECT_ONE, Strategy.DISCARD_ALL_BUT_ONE],
        [
            random_mail_1,
            random_mail_2,
            random_mail_2,
            random_mail_1,
            random_mail_3,
            random_mail_2,
        ],
        [
            random_mail_1,
            random_mail_2,
            random_mail_3,
        ],
    ),

]


@pytest.mark.parametrize(
    ("strategy", "mailbox_input", "mailbox_results"),
    [
        pytest.param(
            strategy,
            mailbox_input,
            mailbox_results,
            id=f"{case_id}|{strategy}",
        )
        for case_id, strategies, mailbox_input, mailbox_results in test_cases
        for strategy in strategies
    ],
)
def test_maildir_strategy(
    invoke,
    make_box,
    strategy,
    mailbox_input,
    mailbox_results,
):
    """Generic test to check the result of a selection strategy."""
    box_path, box_type, _ = make_box(Maildir, mailbox_input)

    result = invoke(f"--strategy={strategy}", "--action=delete-selected", box_path)

    assert result.exit_code == 0
    check_box(box_path, box_type, content=mailbox_results)


@pytest.mark.parametrize(
    ("strategy_id", "mailbox_input", "mailbox_results"),
    [
        pytest.param(
            strategy_id,
            mailbox_input,
            mailbox_results,
            id=f"{case_id}|{strategy_id}",
        )
        for case_id, strategy_ids, mailbox_input, mailbox_results in select_test_cases
        for strategy_id in strategy_ids
    ],
)
def test_maildir_strategy_selected(
    invoke,
    make_box,
    strategy_id,
    mailbox_input,
    mailbox_results,
):
    """Generic test to check the result of a selection strategy."""
    box_path, box_type, dest_box_path = make_box(Maildir, mailbox_input)

    result = invoke(f"--strategy={strategy_id}", "--action=copy-selected",
                    box_path, f"--export={dest_box_path}", "--export-format=maildir")

    assert result.exit_code == 0
    check_box(dest_box_path, box_type, content=mailbox_results)
