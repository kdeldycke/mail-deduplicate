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

"""Checks on the documentation pages that list parts of the test suite."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
"""Directory of the test suite."""

TESTS_PAGE = TESTS_DIR.parent / "docs" / "tests.md"
"""Documentation page with one section per module of the test suite."""


@pytest.mark.once
def test_every_test_module_has_a_section():
    """`docs/tests.md` has one section for each module of the test suite, and no
    other.

    No job generates those sections: a module added to `tests/` stays out of the
    published page until someone writes its section.
    """
    # The sdist ships the test suite but not the documentation sources.
    if not TESTS_PAGE.is_file():
        pytest.skip("The documentation sources are not part of this tree.")

    page = TESTS_PAGE.read_text(encoding="UTF-8")
    documented = set(re.findall(r"^\.\. automodule:: (\S+)$", page, flags=re.MULTILINE))
    modules = {"tests"} | {
        f"tests.{path.stem}"
        for path in TESTS_DIR.glob("*.py")
        if path.stem != "__init__"
    }

    missing = sorted(modules - documented)
    stale = sorted(documented - modules)
    assert not missing, f"`docs/tests.md` has no section for: {missing}."
    assert not stale, f"`docs/tests.md` documents modules that do not exist: {stale}."
