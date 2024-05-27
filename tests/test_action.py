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

from string import ascii_lowercase

from mail_deduplicate.action import ACTIONS


def test_action_definitions():
    """Test duplicate action definitions."""
    for action_id, method in ACTIONS.items():
        # All actions are lower cases strings, with dashes.
        assert isinstance(action_id, str)
        assert set(action_id).issubset(ascii_lowercase + "-")
        assert callable(method)
