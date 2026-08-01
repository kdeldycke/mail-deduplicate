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

from mailbox import Maildir, mbox
from pathlib import Path
from string import ascii_lowercase

import pytest

from mail_deduplicate.action import Action
from mail_deduplicate.deduplicate import Deduplicate, Stat

from .conftest import MailFactory, check_box


def test_action_definitions():
    """Test duplicate action definitions."""
    for action in Action:
        assert isinstance(action.value, str)
        assert set(action.value).issubset(ascii_lowercase + "-")
        assert str(action) == action.value
        assert action.name.lower().replace("_", "-") == action.value

        action_func = action.action_function
        assert action_func is not None
        assert callable(action_func)
        assert action_func.__name__ == action.name.lower()


duplicate_mail = MailFactory(body="Shared duplicate body.\n")
unique_mail = MailFactory(
    message_id="<no-copies-anywhere@example.com>", body="Unique body.\n"
)

# A box of three copies plus one unique mail. Under select-one, one copy is kept, so
# the selection is {unique, one copy} and the discard is {two copies}. The counts stay
# distinct (2 vs 2 vs 4), so no metric coincidentally equals another in the self-check.
FULL_BOX = [duplicate_mail, duplicate_mail, duplicate_mail, unique_mail]
SELECTION = [duplicate_mail, unique_mail]
"""Mails the selection resolves to: the unique mail plus one surviving copy."""
DISCARD = [duplicate_mail, duplicate_mail]
"""Mails the discard resolves to: the two other copies."""


@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry_run"])
@pytest.mark.parametrize(
    ("action", "needs_export", "source_after", "export_after"),
    (
        pytest.param("copy-selected", True, FULL_BOX, SELECTION, id="copy-selected"),
        pytest.param("copy-discarded", True, FULL_BOX, DISCARD, id="copy-discarded"),
        pytest.param("move-selected", True, DISCARD, SELECTION, id="move-selected"),
        pytest.param("move-discarded", True, SELECTION, DISCARD, id="move-discarded"),
        pytest.param("delete-selected", False, DISCARD, None, id="delete-selected"),
        pytest.param("delete-discarded", False, SELECTION, None, id="delete-discarded"),
    ),
)
def test_action_matrix(
    invoke, make_box, action, needs_export, source_after, export_after, dry_run
):
    """Every action lands the right mails in the right box, and the stats self-check
    stays consistent, in real and dry-run mode alike.

    Copy actions leave the source intact; move and delete actions strip it down to
    whichever subset they did not act on. Export actions also cover the re-reading of
    full messages from the source boxes, as mails are dehydrated to lightweight stubs
    once hashed: a regression there would export empty or truncated mails.
    """
    box_path, box_type, export_path = make_box(Maildir, FULL_BOX)

    args = ["--strategy=select-one", f"--action={action}", box_path]
    if needs_export:
        args.append(f"--export={export_path}")
    if dry_run:
        args.insert(0, "--dry-run")
    result = invoke(*args)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr

    if dry_run:
        # Nothing is touched: source intact and no export box created.
        check_box(box_path, box_type, content=FULL_BOX)
        if needs_export:
            assert not Path(export_path).exists()
    else:
        check_box(box_path, box_type, content=source_after)
        if needs_export:
            check_box(export_path, mbox, content=export_after)


@pytest.mark.parametrize(
    ("operator", "found", "retained"),
    (
        pytest.param(">=", 1, 5, id="ge-violated"),
        pytest.param("==", 3, 5, id="eq-violated"),
        pytest.param("bogus", 5, 5, id="unknown-operator"),
    ),
)
def test_assert_stats_inconsistent_exits(config, operator, found, retained):
    """An inconsistent, or uncomparable, metric aborts with the 115 exit code."""
    dedup = Deduplicate(config)
    dedup.stats[Stat.MAIL_FOUND] = found
    dedup.stats[Stat.MAIL_RETAINED] = retained

    with pytest.raises(SystemExit) as exc:
        dedup.assert_stats(Stat.MAIL_FOUND, operator, Stat.MAIL_RETAINED)
    assert exc.value.code == 115


def test_assert_stats_consistent_passes(config):
    """A satisfied assertion returns quietly, without exiting."""
    dedup = Deduplicate(config)
    dedup.stats[Stat.MAIL_FOUND] = 5
    dedup.stats[Stat.MAIL_RETAINED] = 3

    dedup.assert_stats(Stat.MAIL_FOUND, ">=", Stat.MAIL_RETAINED)


def test_unique_only_source_is_exported(invoke, make_box):
    """A source made only of unique mails still exports all of them: a set of one mail
    is auto-selected, not skipped as "all mails were selected".

    See: https://github.com/kdeldycke/mail-deduplicate/issues/843 and
    https://github.com/kdeldycke/mail-deduplicate/issues/599
    """
    uniques = [
        MailFactory(message_id=f"<uniq-{i}@nohost.com>", body=f"Body {i}\n")
        for i in range(3)
    ]
    box_path, _, export_path = make_box(Maildir, uniques)

    result = invoke(
        "--strategy=select-one",
        "--action=copy-selected",
        f"--export={export_path}",
        box_path,
    )

    assert result.exit_code == 0
    # All three unique mails were copied to the export box, none skipped.
    check_box(export_path, mbox, content=uniques)
