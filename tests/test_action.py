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

from mail_deduplicate.action import Action

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


duplicate_mail = MailFactory()
unique_mail = MailFactory(message_id="<no-copies-anywhere@example.com>")


@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry_run"])
def test_discarded_action_stats(invoke, make_box, dry_run):
    """A ``*-discarded`` action targets the discarded mails, so its counter differs
    from the number of unique and selected mails. The final statistics self-check
    must account for it, in dry-run mode too.

    The box mixes a unique mail with a set of 4 copies, so no counter coincidentally
    equals another.
    """
    box_path, box_type, _ = make_box(
        Maildir,
        [duplicate_mail, duplicate_mail, duplicate_mail, duplicate_mail, unique_mail],
    )

    args = ["--strategy=select-one", "--action=delete-discarded", box_path]
    if dry_run:
        args.insert(0, "--dry-run")
    result = invoke(*args)

    assert result.exit_code == 0
    assert "Metrics appear inconsistent" not in result.stderr

    if dry_run:
        expected = [duplicate_mail] * 4 + [unique_mail]
    else:
        # One arbitrary copy of the duplicated mail survives, next to the unique mail.
        expected = [duplicate_mail, unique_mail]
    check_box(box_path, box_type, content=expected)
