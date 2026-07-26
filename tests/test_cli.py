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

import pytest
from click_extra import BUILTIN_THEMES
from click_extra.test_suite import load_test_suite, run_test_suite

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


@pytest.mark.once
def test_cli_test_suite():
    """Run the TOML black-box suite (cli-test-suite.toml) against the installed mdedup.

    Each case is executed as a subprocess by click-extra's test-suite runner, so this
    exercises the real entry point (version reporting, help screen rendering).

    Marked ``once``: the CI matrix drives the same TOML suite in every cell through
    click-extra's runner, so this Python-level wrapper only needs a single executor.
    """
    suite = Path(__file__).parent / "cli-test-suite.toml"
    cases = list(load_test_suite(suite))
    assert cases, "Empty test suite: cli-test-suite.toml parsed to zero cases."
    result = run_test_suite("mdedup", cases)
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


@pytest.mark.parametrize("box_type", (Maildir, mbox))
def test_hash_only_prints_headers(invoke, make_box, box_type):
    """``--hash-only`` must print each mail's canonical headers and hash, not crash.

    Regression test: the display loop referenced a non-existent ``mail.pretty_headers``
    attribute, so ``--hash-only`` died with ``AttributeError`` on the first mail.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/1004
    """
    box_path, _, export_path = make_box(
        box_type,
        [MailFactory(message_id="<a@nohost.com>")],
    )

    # --export satisfies the default copy-selected action's requirement; --hash-only
    # exits before any action runs, so nothing is written there.
    result = invoke("--hash-only", "--export", export_path, box_path)

    assert result.exit_code == 0
    # The canonical-headers table and the computed hash are printed for the mail.
    assert "Header ID" in result.stdout
    assert "Hash:" in result.stdout


def test_single_hash_header_needs_no_minimal_flag(invoke, make_box):
    """A single ``--hash-header`` must work without a separate minimal-headers flag.

    Regression test: narrowing the hash below four headers used to raise "Provided
    number of headers to hash (1) is less than the minimal required number of headers
    (4)" and then reject every mail. The floor is now derived as
    ``min(4, number of --hash-header values)``, so a lone header is enough.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/974
    """
    box_path, _, export_path = make_box(
        Maildir,
        [MailFactory(message_id="<solo@nohost.com>")],
    )

    result = invoke(
        "--hash-header",
        "message-id",
        "--hash-only",
        "--export",
        export_path,
        box_path,
    )

    assert result.exit_code == 0
    # The mail is hashed rather than rejected by the minimal-headers floor.
    assert "Hash:" in result.stdout
    assert "Rejecting" not in result.stderr
