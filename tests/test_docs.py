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

"""Checks on the documentation pages that list parts of the test suite, and on the
assets the readme illustrates itself with.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
"""Directory of the test suite."""

PROJECT_ROOT = TESTS_DIR.parent
"""Repository root."""

TESTS_PAGE = PROJECT_ROOT / "docs" / "tests.md"
"""Documentation page with one section per module of the test suite."""

ASSETS_DIR = PROJECT_ROOT / "docs" / "assets"
"""Directory holding the pictures the readme and the docs embed."""


def _cli_screenshots():
    """Load `docs/cli_screenshots_update.py` by path, `docs` being no package."""
    spec = importlib.util.spec_from_file_location(
        "cli_screenshots_update",
        PROJECT_ROOT / "docs" / "cli_screenshots_update.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _pages_embedding(stem: str) -> list[Path]:
    """The readme and docs pages that embed the capture named `stem`."""
    pages = [PROJECT_ROOT / "readme.md", *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
    return [
        page
        for page in pages
        if f"assets/{stem}.svg" in page.read_text(encoding="UTF-8")
    ]


@pytest.mark.once
def test_every_cli_capture_is_embedded():
    """Each capture `docs/cli_screenshots_update.py` writes is embedded in the
    readme or a docs page, and no SVG in `docs/assets/` outlives the capture that
    produced it.

    The stems of the captures are the file names the pages link, so renaming one
    in the script breaks a page silently: GitHub serves a 404 where the readme's
    picture was, and nothing in a docs build reads that URL. The reverse direction
    rots the same way: a capture dropped from the script leaves its SVG in the
    tree, unreferenced and never refreshed again.
    """
    if not ASSETS_DIR.is_dir():
        pytest.skip("The documentation sources are not part of this tree.")

    captures = _cli_screenshots().CAPTURES
    assert captures, "no capture left in docs/cli_screenshots_update.py"

    unlinked = [entry.stem for entry in captures if not _pages_embedding(entry.stem)]
    assert not unlinked, f"no page embeds a picture of: {unlinked}."

    stems = {entry.stem for entry in captures}
    orphans = [path.name for path in ASSETS_DIR.glob("*.svg") if path.stem not in stems]
    assert not orphans, f"SVGs no capture produces: {orphans}."


@pytest.mark.once
def test_pages_show_the_command_their_picture_runs():
    """A page embedding a capture shows the command line the capture ran.

    The picture and the command sit side by side, and a reader compares them: an
    option changed in one and not the other reads as the picture disagreeing with
    the instructions. Nothing compares the two, since the command is prose to
    every other check here.

    A capture forcing an error is the exception: its command reproduces nothing
    on a reader's boxes, so its page explains the picture instead.
    """
    if not ASSETS_DIR.is_dir():
        pytest.skip("The documentation sources are not part of this tree.")

    for entry in _cli_screenshots().CAPTURES:
        if entry.injected:
            continue
        command = shlex.join(("mdedup", *entry.args))
        for page in _pages_embedding(entry.stem):
            assert command in page.read_text(encoding="UTF-8"), (
                f"{page.relative_to(PROJECT_ROOT)} embeds {entry.stem} but never "
                f"shows the command it pictures: {command}"
            )


@pytest.mark.once
def test_cli_capture_prompts_fit_their_window():
    """Every captured command line fits its window on one row.

    `docs/cli_screenshots_update.py` rejects an over-long invocation before it
    draws one, but the guard only runs when someone recaptures by hand. This
    reads the same budget from the committed capture instead, so an option added
    to a capture and not to its picture cannot land unnoticed.

    A wrapped prompt reads as two commands, and the second one opens mid-option:
    the picture would teach an invocation nobody can type.
    """
    module = _cli_screenshots()
    for entry in module.CAPTURES:
        # A still capture's wrap marker takes the last cell of every row, the
        # prompt's included. A recording draws none.
        budget = module.prompt_budget(entry)
        row = module.PROMPT_SIGIL + shlex.join(("mdedup", *entry.args))
        assert len(row) <= budget, (
            f"the prompt of {entry.stem} measures {len(row)} characters against "
            f"the {budget} its window leaves, so it wraps onto a second row: {row}"
        )


@pytest.mark.once
def test_self_referencing_urls_name_a_file_the_tree_holds():
    """A `raw.githubusercontent.com` URL pointing at this repository's own `main`
    names a file the tree still carries.

    Nothing else resolves these: they are fetched by a reader far from any test,
    on GitHub and on PyPI, where the readme is the whole page. Renaming a file
    under `docs/assets/` therefore breaks every surface at once, with no build
    and no link check in between.

    A URL pinned to a tag names a historical tree and is skipped, the working
    copy being no evidence about what that tag held.
    """
    url_re = re.compile(
        r"https://raw\.githubusercontent\.com/kdeldycke/mail-deduplicate/"
        r"(?:refs/heads/)?main/(?P<path>[^\s<>\"')|]+)"
    )
    files = [
        *sorted((PROJECT_ROOT / "mail_deduplicate").rglob("*.py")),
        *sorted((PROJECT_ROOT / "tests").glob("*.py")),
        *sorted((PROJECT_ROOT / "docs").glob("*.md")),
        PROJECT_ROOT / "readme.md",
    ]
    hits = []
    for path in files:
        if not path.is_file():
            continue
        lines = path.read_text(encoding="UTF-8").splitlines()
        for lineno, line in enumerate(lines, 1):
            for match in url_re.finditer(line):
                target = match.group("path")
                if not (PROJECT_ROOT / target).is_file():
                    source = path.relative_to(PROJECT_ROOT)
                    hits.append(f"{source}:{lineno} names {target}")
    assert not hits, "URLs naming a file the tree no longer holds:\n" + "\n".join(hits)
