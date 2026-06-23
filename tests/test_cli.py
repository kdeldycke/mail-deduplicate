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
from pathlib import Path

import pytest
from click_extra import BUILTIN_THEMES
from click_extra.test_plan import parse_test_plan, run_test_plan

from .conftest import MailFactory


def test_bare_call(invoke):
    result = invoke()
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_early_export_file_check(invoke, make_box, tmp_path):
    """Ensures the export file is tested for existence before any process is ran.

    See: https://github.com/kdeldycke/mail-deduplicate/issues/119
    """
    box_path, _, _ = make_box(Maildir)

    result = invoke("--export=non_existing.file", box_path)
    assert result.exit_code == 0
    assert "0 mails found." in result.stderr
    assert "● Step #1" in result.stdout
    assert "non_existing.file" not in result.stderr

    file = tmp_path.joinpath("existing.file")
    file.touch()
    result = invoke(f"--export={file!s}", box_path)
    assert result.exit_code == 1
    # The export-existence check fails before any box is opened or scanned. (Parsing
    # the eager --jobs option logs its resolution, so stderr is not strictly empty.)
    assert "Opening" not in result.stderr
    assert "mails found" not in result.stderr
    assert isinstance(result.exception, FileExistsError)
    assert (
        str(result.exception)
        == f"Cannot export to existing file {file!r} unless --export-append is set."
    )


@pytest.mark.parametrize("theme_id", ("dark", "light"))
def test_theme_styles_runtime_output(invoke, make_box, theme_id):
    """The active ``--theme`` must style runtime output, not just the help screen.

    Regression test: the theme used to be captured once at import time via
    ``get_default_theme()``, so ``--theme`` was ignored everywhere but ``--help``.
    """
    box_path, _, export_path = make_box(Maildir)

    # --color=always forces click-extra to resolve the color mode on (the runner
    # is not a real terminal), and color=True keeps the ANSI codes in the captured
    # output instead of stripping them.
    result = invoke(
        "--theme",
        theme_id,
        "--color=always",
        "--export",
        export_path,
        box_path,
        color=True,
    )
    assert result.exit_code == 0

    # The Step #1 heading must carry the styling of the selected theme.
    styled_heading = BUILTIN_THEMES[theme_id].heading("\n● Step #1 - Load mails")
    assert styled_heading in result.stdout


def test_cli_test_plan():
    """Run the YAML black-box plan (cli-test-plan.yaml) against the installed mdedup.

    Each case is executed as a subprocess by click-extra's test_plan runner, so this
    exercises the real entry point (version reporting, help screen rendering).
    """
    plan = (Path(__file__).parent / "cli-test-plan.yaml").read_text(encoding="utf-8")
    cases = list(parse_test_plan(plan))
    assert cases, "Empty test plan: cli-test-plan.yaml parsed to zero cases."
    result = run_test_plan("mdedup", cases)
    assert result["failed"] == 0


def test_parallel_hashing_matches_sequential(invoke, make_box):
    """Hashing with --jobs > 1 must yield the same dedup result as the sequential
    default. Reading stays single-threaded and run_jobs preserves submission order,
    so the grouping, stats, and report must be identical at any job count.
    """
    # Three duplicate pairs (distinct Message-IDs give three hash groups; each mail
    # repeated makes each group a genuine duplicate set).
    pairs = [
        MailFactory(message_id="<a@nohost.com>"),
        MailFactory(message_id="<b@nohost.com>"),
        MailFactory(message_id="<c@nohost.com>"),
    ]
    box_path, _, _ = make_box(Maildir, [mail for mail in pairs for _ in range(2)])

    # --dry-run leaves the box untouched, so both invocations see identical input.
    args = (
        "--strategy=select-newest",
        "--action=delete-selected",
        "--dry-run",
        box_path,
    )
    sequential = invoke(*args)
    parallel = invoke("--jobs=2", *args)

    assert sequential.exit_code == 0
    assert parallel.exit_code == 0
    assert parallel.stdout == sequential.stdout
