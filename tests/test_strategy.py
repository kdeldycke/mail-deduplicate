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

import pytest
from whenever import Instant

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
        docstring = strategy.strategy_function.__doc__
        assert docstring and docstring.strip()


# Time-based collection of pre-defined fixtures.
now = Instant.now()
newest_mail = MailFactory(date=now)
newer_mail = MailFactory(date=now.subtract(minutes=1))
older_mail = MailFactory(date=now.subtract(minutes=2))
oldest_mail = MailFactory(date=now.subtract(minutes=3))


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


# The full spread of time-, size- and quantity-based fixtures, each present twice so
# every strategy has a duplicate set to act on. Reused as both the box input and, in
# dry-run, the expected untouched content.
ALL_FIXTURE_MAILS = [
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
]


# List of strategies and their required dummy parameters.
strategy_options: dict[str, list[str]] = {key: [] for key in map(str, Strategy)}
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
    box_path, box_type, _ = make_box(Maildir, ALL_FIXTURE_MAILS)

    result = invoke(
        f"--strategy={strategy_id}",
        *params,
        "--action=delete-selected",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 0
    check_box(box_path, box_type, content=ALL_FIXTURE_MAILS)


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


undated_mail = MailFactory(date_rfc2822="Not a date")
"""A mail with an unparseable `Date` header, from which no timestamp can be
derived."""


def test_strategy_fallback_resolves_identical_copies(invoke, make_box):
    """Time-based strategies cannot discriminate byte-identical copies: the next
    strategy of the cascade takes over the sets they fail on.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/647
    """
    box_path, box_type, _ = make_box(
        Maildir,
        [
            # A set of copies discriminable by their timestamps.
            oldest_mail,
            newest_mail,
            # A set of identical copies, sharing the same timestamp.
            random_mail_1,
            random_mail_1,
        ],
    )

    result = invoke(
        "--strategy=select-oldest",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    # Only the identical pair was handed over to the fallback strategy.
    assert result.stderr.count("Fall back to the next strategy...") == 1
    # select-oldest resolved the dated pair, select-one the identical pair.
    check_box(box_path, box_type, content=[oldest_mail, random_mail_1])


def test_strategy_fallback_on_missing_timestamp(invoke, make_box):
    """A set whose mails have no parseable timestamp is handed over to the next
    strategy of the cascade instead of being skipped."""
    box_path, box_type, _ = make_box(Maildir, [undated_mail, undated_mail])

    result = invoke(
        "--strategy=select-oldest",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert "cannot compare mails without a timestamp" in result.stderr
    assert "Fall back to the next strategy..." in result.stderr
    check_box(box_path, box_type, content=[undated_mail])


def test_strategy_cascade_exhausted(invoke, make_box):
    """A set failing every strategy of the cascade is skipped as a whole."""
    box_path, box_type, _ = make_box(Maildir, [random_mail_1, random_mail_1])

    result = invoke(
        "--strategy=select-older",
        "--strategy=select-newer",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0
    assert result.stderr.count("Fall back to the next strategy...") == 1
    assert "Skip set: No mail within were selected." in result.stderr
    check_box(box_path, box_type, content=[random_mail_1, random_mail_1])


def test_time_strategy_alone_cannot_split_same_timestamp_set(invoke, make_box):
    """A time-based strategy selects the whole set when every mail shares a timestamp,
    which discriminates nothing, so the set is skipped and no mail is deleted. A
    fallback strategy is the documented way to resolve such sets.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/270 and
    https://github.com/kdeldycke/mail-deduplicate/issues/647
    """
    box_path, box_type, _ = make_box(
        Maildir, [random_mail_1, random_mail_1, random_mail_1]
    )

    # discard-newer is an alias of select-oldest: on three same-timestamp copies it
    # selects all of them, discriminating nothing.
    result = invoke(
        "--strategy=discard-newer",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert "all 3 mails within were selected" in result.stderr
    # Nothing was discriminated, so nothing was deleted.
    check_box(box_path, box_type, content=[random_mail_1, random_mail_1, random_mail_1])


def test_strategy_cascade_dedup_aliases(invoke, make_box):
    """Repeated strategies are collapsed into one, even under their aliases."""
    box_path, box_type, _ = make_box(Maildir, [oldest_mail, newest_mail])

    result = invoke(
        "--strategy=select-oldest",
        "--strategy=select-oldest",
        "--strategy=discard-newer",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    # The chain was reduced to a single strategy, reported in the singular.
    assert "strategy will be applied" in result.stderr
    assert "strategies will be applied" not in result.stderr
    check_box(box_path, box_type, content=[oldest_mail])


def test_strategy_cascade_regexp_required(invoke, make_box):
    """--regexp is required as soon as a path-based strategy is part of the
    cascade."""
    box_path, _, _ = make_box(Maildir, [random_mail_1, random_mail_1])

    result = invoke(
        "--strategy=select-oldest",
        "--strategy=select-matching-path",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 2
    assert (
        "when -s/--strategy is one of discard-matching-path, "
        "discard-non-matching-path, select-matching-path, select-non-matching-path, "
        "--regexp is required" in result.stderr
    )


def test_strategy_cascade_regexp_not_allowed(invoke, make_box):
    """--regexp is rejected when no strategy of the cascade makes use of it."""
    box_path, _, _ = make_box(Maildir, [random_mail_1, random_mail_1])

    result = invoke(
        "--strategy=select-oldest",
        "--strategy=select-one",
        "--regexp=.*",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 2
    assert (
        "when -s/--strategy is none of discard-matching-path, "
        "discard-non-matching-path, select-matching-path, select-non-matching-path, "
        "the following parameters should not be provided:" in result.stderr
    )
    assert "--regexp (-r)" in result.stderr


outlier_mail = MailFactory(body="An entirely different mail body. " * 60)
"""A mail whose body size and content exceed the default thresholds against the
other fixtures."""


def test_outlier_eviction_keeps_core_dedup(invoke, make_box):
    """A mail exceeding the thresholds against its set no longer prevents the
    deduplication of the true copies sharing the set.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/851
    """
    box_path, box_type, _ = make_box(
        Maildir,
        [smallest_mail, smallest_mail, outlier_mail],
    )

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "Set aside 1 mails too dissimilar" in result.stderr
    assert "--hash-header" in result.stderr

    # One of the two identical copies was deleted, the outlier was left untouched.
    check_box(box_path, box_type, content=[smallest_mail, outlier_mail])


def test_dissimilar_pair_still_skipped(invoke, make_box):
    """A set with no coherent core of at least 2 similar mails is skipped as a whole,
    like before outlier eviction was introduced."""
    box_path, box_type, _ = make_box(Maildir, [smallest_mail, outlier_mail])

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "Skip set: mails are too dissimilar in size." in result.stderr

    # No mail was removed.
    check_box(box_path, box_type, content=[smallest_mail, outlier_mail])


def test_eviction_is_not_transitive(invoke, make_box):
    """A chain of mails, each within threshold of the next but not of the whole set,
    is not collapsed into a single group: an endpoint is set aside, and the coherent
    remainder is deduplicated."""
    chain = [
        MailFactory(body="z" * 100),
        MailFactory(body="z" * 500),
        MailFactory(body="z" * 900),
    ]
    box_path, _, _ = make_box(Maildir, chain)

    result = invoke(
        "--content-threshold=-1",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert "Set aside 1 mails too dissimilar" in result.stderr

    # The evicted endpoint remains, plus one survivor of the two-mail core.
    assert len(Maildir(box_path, create=False)) == 2


@pytest.mark.parametrize(
    ("extra_args", "size_skip_logged", "content_skip_logged"),
    (
        pytest.param(("--size-threshold=-1",), True, False, id="size-disabled"),
        pytest.param(("--content-threshold=-1",), False, True, id="content-disabled"),
        pytest.param(
            ("--size-threshold=-1", "--content-threshold=-1"),
            True,
            True,
            id="both-disabled",
        ),
    ),
)
def test_threshold_checks_disabled(
    invoke, make_box, extra_args, size_skip_logged, content_skip_logged
):
    """A threshold set to -1 turns off its similarity check, and logs that it did.

    The identical pair deduplicates whatever the thresholds; the flags only govern
    whether the size and content guards run at all.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/97
    """
    box_path, box_type, _ = make_box(Maildir, [random_mail_1, random_mail_1])

    result = invoke(
        *extra_args,
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert ("Skip checking for size differences." in result.stderr) is size_skip_logged
    assert (
        "Skip checking for content differences." in result.stderr
    ) is content_skip_logged
    # The identical pair is still deduplicated down to a single mail.
    check_box(box_path, box_type, content=[random_mail_1])


def test_no_strategy_skips_duplicate_sets(invoke, make_box):
    """With no --strategy, duplicate sets are grouped and counted, then skipped whole,
    so every mail stays in place."""
    box_path, box_type, _ = make_box(Maildir, [random_mail_1, random_mail_1])

    result = invoke("--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "no strategy to apply" in result.stderr
    check_box(box_path, box_type, content=[random_mail_1, random_mail_1])


def test_content_dissimilar_pair_skipped_without_diff(invoke, make_box):
    """A content-dissimilar set is skipped whole; without --show-diff, no unified diff
    is printed for it."""
    # Same headers group them; equal-length bodies keep the size check quiet so the
    # content check is what trips.
    a = MailFactory(date="2021-01-01", message_id="<cd@nohost.com>", body="aaaa bbbb\n")
    b = MailFactory(date="2021-01-01", message_id="<cd@nohost.com>", body="cccc dddd\n")
    box_path, box_type, _ = make_box(Maildir, [a, b])

    result = invoke(
        "--content-threshold=0",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 0
    assert "too dissimilar in content" in result.stderr
    assert "@@" not in result.stderr  # no unified-diff hunk header without --show-diff
    check_box(box_path, box_type, content=[a, b])
