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

import sys
import tracemalloc
from mailbox import Maildir, mbox
from pathlib import Path

import pytest
from click_extra import BUILTIN_THEMES
from click_extra.test_suite import load_test_suite, run_test_suite

from mail_deduplicate.mail import DedupMailMixin

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
    """The active `--theme` must style runtime output, not just the help screen.

    Regression test: the theme used to be captured once at import time via
    `get_default_theme()`, so `--theme` was ignored everywhere but `--help`.
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

    Marked `once`: the CI matrix drives the same TOML suite in every cell through
    click-extra's runner, so this Python-level wrapper only needs a single executor.
    """
    suite = Path(__file__).parent / "cli-test-suite.toml"
    cases = list(load_test_suite(suite))
    assert cases, "Empty test suite: cli-test-suite.toml parsed to zero cases."
    result = run_test_suite("mdedup", cases)
    assert result["failed"] == 0


@pytest.mark.parametrize(
    "strategy",
    (
        # Time-based, and the one that fails to discriminate identical copies.
        "select-newest",
        # Size-based, which pulls each mail's body back to measure it.
        "select-smallest",
        # Path-based, which needs a mail's location: a worker has no box to derive
        # that from, and reads it off the file it opened instead.
        "select-matching-path",
        # Arbitrary pick. Which copy it lands on differs between processes, since
        # each seeds its own randomness, but how many it picks does not.
        "select-one",
    ),
)
def test_parallel_run_matches_sequential(invoke, make_box, strategy):
    """A run with --jobs > 1 must decide what the sequential default decides.

    Both the hashing and the selection are handed to worker processes, and both
    yield their results in submission order, so the grouping, the statistics and the
    report must come out identical at any job count.
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
    # --regexp is only accepted by the path-matching strategies.
    args = (
        f"--strategy={strategy}",
        *(("--regexp=.*",) if "matching-path" in strategy else ()),
        "--action=delete-selected",
        "--dry-run",
        box_path,
    )
    sequential = invoke(*args)
    parallel = invoke("--jobs=2", *args)

    assert sequential.exit_code == 0
    assert parallel.exit_code == 0
    assert parallel.stdout == sequential.stdout


@pytest.mark.parametrize("jobs", ("1", "2"))
def test_memory_stays_bounded_while_hashing(invoke, make_box, jobs):
    """Peak memory must track the few mails in flight, not the whole corpus.

    Regression test for the out-of-memory conditions reported on big boxes: mails
    used to be retained fully parsed for the whole run, so memory grew linearly with
    the corpus. They are now dehydrated as soon as they are hashed, and the parallel
    path materializes mails in bounded batches instead of the whole corpus.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/761
    """
    body = "x" * 100_000
    mails = [
        MailFactory(body=body, message_id=f"<big-{index}@nohost.com>")
        for index in range(300)
    ]
    box_path, _, _ = make_box(Maildir, mails)
    corpus_bytes = sum(len(mail.render()) for mail in mails)

    tracemalloc.start()
    result = invoke(
        f"--jobs={jobs}",
        "--strategy=select-newest",
        "--action=delete-discarded",
        "--dry-run",
        box_path,
    )
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert result.exit_code == 0
    assert peak < corpus_bytes / 2


@pytest.mark.parametrize("box_type", (Maildir, mbox))
def test_hash_only_prints_headers(invoke, make_box, box_type):
    """`--hash-only` must print each mail's canonical headers and hash, not crash.

    Regression test: the display loop referenced a non-existent `mail.pretty_headers`
    attribute, so `--hash-only` died with `AttributeError` on the first mail.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/1004
    """
    box_path, _, _export_path = make_box(
        box_type,
        [MailFactory(message_id="<a@nohost.com>")],
    )

    # No --export: hash-only mode exits before any action runs, so the default
    # copy-selected action's requirements must not be enforced.
    result = invoke("--hash-only", box_path)

    assert result.exit_code == 0
    # The canonical-headers table and the computed hash are printed for the mail.
    assert "Header ID" in result.stdout
    assert "Hash:" in result.stdout


def test_single_hash_header_needs_no_minimal_flag(invoke, make_box):
    """A single `--hash-header` must work without a separate minimal-headers flag.

    Regression test: narrowing the hash below four headers used to raise "Provided
    number of headers to hash (1) is less than the minimal required number of headers
    (4)" and then reject every mail. The floor is now derived as
    `min(4, number of --hash-header values)`, so a lone header is enough.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/974
    """
    box_path, _, _export_path = make_box(
        Maildir,
        [MailFactory(message_id="<solo@nohost.com>")],
    )

    result = invoke(
        "--hash-header",
        "message-id",
        "--hash-only",
        box_path,
    )

    assert result.exit_code == 0
    # The mail is hashed rather than rejected by the minimal-headers floor.
    assert "Hash:" in result.stdout
    assert "Rejecting" not in result.stderr


def test_too_few_headers_rejects_mail(invoke, make_box):
    """A mail carrying fewer hash headers than the floor is rejected, and the warning
    renders the headers that were found so the mail can be inspected.

    The floor is derived as `min(4, number of --hash-header values)`, so asking for
    four headers the mail does not carry leaves it one below the floor.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke(
        "--hash-header=x-absent-one",
        "--hash-header=x-absent-two",
        "--hash-header=x-absent-three",
        "--hash-header=subject",
        "--hash-only",
        box_path,
    )

    assert result.exit_code == 0
    assert "Rejecting" in result.stderr
    assert "1 headers found out of 4" in result.stderr
    # The table of the headers that were found is rendered alongside the warning.
    assert "Header ID" in result.stderr
    # Being rejected, the mail never reaches the hashing step.
    assert "Hash:" not in result.stdout


def test_headers_table_rendered_only_when_logged(invoke, make_box, monkeypatch):
    """Rendering the canonical-headers table goes through `tabulate` and costs more
    than the hash itself, yet it is discarded at any level above debug. It must not
    be built at all at the default verbosity."""
    renders: list[str] = []
    original = DedupMailMixin.pretty_canonical_headers

    def spy(self) -> str:
        rendered = original(self)
        renders.append(rendered)
        return rendered

    monkeypatch.setattr(DedupMailMixin, "pretty_canonical_headers", spy)
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])
    args = ("--strategy=select-newest", "--action=delete-selected", "--dry-run")

    assert invoke(*args, box_path).exit_code == 0
    assert renders == []

    assert invoke("--verbosity=DEBUG", *args, box_path).exit_code == 0
    # Both mails have enough headers, so each one renders its table exactly once.
    assert len(renders) == 2


def test_invalid_hash_header_rejected(invoke, make_box):
    """A header ID with out-of-range characters is refused at parse time."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    # The space (ASCII 32) falls below the RFC-5322 printable range.
    result = invoke("--hash-header", "bad header", box_path)

    assert result.exit_code == 2
    assert "invalid header ID" in result.stderr


def test_invalid_regexp_rejected(invoke, make_box):
    """An un-compilable regular expression is refused at parse time."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke("--strategy=select-matching-path", "--regexp=[", box_path)

    assert result.exit_code == 2
    assert "invalid regular expression" in result.stderr


def test_duplicate_source_rejected(invoke, make_box):
    """The same mail source given twice is refused: the source path is the key used to
    tie a mail back to its origin."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke(
        "--strategy=select-one", "--action=delete-discarded", box_path, box_path
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert "already added" in str(result.exception)


def test_hash_only_warns_about_ignored_options(invoke, make_box):
    """--hash-only runs no selection or action, so options from those steps are
    ignored, and any the user set are reported."""
    box_path, _, _ = make_box(Maildir, [MailFactory(message_id="<h@nohost.com>")])

    result = invoke("--hash-only", "--strategy=select-one", box_path)

    assert result.exit_code == 0
    assert "ignored in -H/--hash-only mode" in result.stderr
    assert "--strategy" in result.stderr


def test_main_entrypoint_reports_version(monkeypatch, capsys):
    """The `main()` indirection runs the CLI end to end: `--version` exits cleanly
    through it."""
    from mail_deduplicate.__main__ import main

    monkeypatch.setattr(sys, "argv", ["mdedup", "--version"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert "mdedup" in capsys.readouterr().out
