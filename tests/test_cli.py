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

import builtins
import multiprocessing
import os
import subprocess
import sys
import tracemalloc
from mailbox import Maildir, mbox
from pathlib import Path

import pytest
from click_extra import BUILTIN_THEMES, unstyle
from click_extra.test_suite import load_test_suite, run_test_suite

from mail_deduplicate.__main__ import WORKER_RERUN_ERROR, main
from mail_deduplicate.cli import PRESET_OPTIONS, Preset
from mail_deduplicate.mail import DedupMailMixin

from .conftest import MailFactory, assert_one_line_error, check_box, metrics


def acted_upon(result) -> list[str]:
    """The lines of a dry run's action trail, one per mail it would act on."""
    return [line for line in result.stderr.splitlines() if "would be " in line]


def test_bare_call(invoke):
    result = invoke()
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


@pytest.mark.parametrize("label", ("Mail sources", "Hashed mails", "Deduplicated sets"))
def test_no_progress_bar_label_off_a_terminal(invoke, make_box, label):
    """Off a terminal, a run prints no progress bar, and so none of its labels.

    Click prints a hidden bar's label once instead of the bar, which put a bare
    line repeating the step heading in every log, pipe and capture.
    """
    box_path, _, export_path = make_box(Maildir)
    result = invoke("--strategy=select-one", f"--export={export_path}", box_path)
    assert result.exit_code == 0
    lines = [line.strip() for line in result.output.splitlines()]
    assert label not in lines


def test_no_log_line_is_left_empty(invoke, make_box):
    """Every log line carries its message on the line of its level prefix."""
    box_path, _, export_path = make_box(Maildir)
    result = invoke("--strategy=select-one", f"--export={export_path}", box_path)
    assert result.exit_code == 0
    assert "info:" not in [line.strip() for line in result.stderr.splitlines()]


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
    assert_one_line_error(
        result,
        f"Error: Cannot export to existing file {file} unless --export-append is set.",
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
    styled_heading = BUILTIN_THEMES[theme_id].heading("● Step #1 - Load mails")
    assert styled_heading in result.stdout

    # No style may span a line break: a line holding nothing but escapes opens a
    # style the next line closes, which a tool cutting the output line by line
    # (a capture's --head, grep) leaves open.
    escape_only = [
        line for line in result.stdout.splitlines() if line and not unstyle(line)
    ]
    assert not escape_only, escape_only


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
        # Keeps the copy whose path sorts first, which a worker reads off the file
        # it opened, as the main process derives it from the box.
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
    # The same mails, not only as many of them.
    assert acted_upon(parallel) == acted_upon(sequential)


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
    # The mail is hashed, where the minimal-headers floor would leave it unhashed.
    assert "Hash:" in result.stdout
    assert "too few headers" not in result.stderr


def test_too_few_headers_leaves_mail_unhashed(invoke, make_box):
    """A mail carrying fewer hash headers than the floor gets no hash.

    The warning renders the headers that were found, so the mail can be inspected.

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
    assert "with too few headers to hash it: 1 headers found out of 4" in result.stderr
    # The table of the headers that were found is rendered alongside the warning.
    assert "Header ID" in result.stderr
    # Unhashed, the mail has no hash to print.
    assert "Hash:" not in result.stdout


def applied_options(result, preset: Preset) -> str:
    """The options a run says it applies for a preset.

    They sit on the log line after the one announcing the preset.
    """
    lines: list[str] = result.stderr.splitlines()
    (index,) = [
        number
        for number, line in enumerate(lines)
        if f"Apply the options of the {preset} preset:" in line
    ]
    return lines[index + 1].removeprefix("info:").strip()


def preset_args(preset: Preset) -> list[str]:
    """The options a preset stands for, as arguments of a command line."""
    return [
        flag if value is True else f"{flag}={value}"
        for flag, value in PRESET_OPTIONS[preset]
    ]


@pytest.mark.parametrize(
    ("preset", "duplicates"),
    (
        pytest.param(Preset.CONSERVATIVE, "2", id="conservative"),
        pytest.param(Preset.DEFAULT, "3", id="default"),
        pytest.param(Preset.AGGRESSIVE, "4", id="aggressive"),
    ),
)
def test_preset_is_an_alias_of_its_options(invoke, make_box, preset, duplicates):
    """A run with a preset decides what a run with the options it stands for decides.

    The box holds what tells the presets apart: two identical copies, a near copy
    sharing every hashed header, and a copy a gateway dated two days later. Each
    preset groups more of them than the one before.
    """
    copy = MailFactory(
        date="2024-05-10", message_id="<garden@nohost.com>", body="Plums.\n"
    )
    near_copy = MailFactory(
        date="2024-05-10",
        message_id="<garden@nohost.com>",
        body="Plums. Unsubscribe: lists.example.com\n",
    )
    redated = MailFactory(
        date="2024-05-12", message_id="<garden@nohost.com>", body="Plums.\n"
    )
    box_path, _, _ = make_box(Maildir, [copy, copy, near_copy, redated])
    args = ("--strategy=select-one", "--action=delete-discarded", "--dry-run")

    aliased = invoke(f"--preset={preset}", *args, box_path)
    expanded = invoke(*preset_args(preset), *args, box_path)

    assert aliased.exit_code == 0
    assert expanded.exit_code == 0
    assert metrics(aliased.stdout)["Duplicates"] == duplicates
    assert aliased.stdout == expanded.stdout
    assert acted_upon(aliased) == acted_upon(expanded)


@pytest.mark.parametrize(
    ("args", "env", "overriding", "dropped"),
    (
        pytest.param(
            ("--hash-body=decoded",),
            {},
            "-b/--hash-body",
            "--hash-body",
            id="command-line",
        ),
        pytest.param(
            (),
            {"MDEDUP_HASH_BODY": "decoded"},
            "-b/--hash-body",
            "--hash-body",
            id="environment",
        ),
        # The header list and the raw headers make one choice.
        pytest.param(
            ("--hash-header=subject",),
            {},
            "-h/--hash-header",
            "--raw-headers",
            id="header-list",
        ),
        pytest.param(
            ("--no-raw-headers",),
            {},
            "--raw-headers/--no-raw-headers",
            "--raw-headers",
            id="negated-flag",
        ),
    ),
)
def test_preset_yields_to_an_option_set_by_the_user(
    invoke, make_box, args, env, overriding, dropped
):
    """An option the user set keeps its value over the one its preset gives it.

    The run names each option that overrides the preset, and leaves the preset's
    value for it out of the options it applies.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke("--preset=conservative", *args, "--hash-only", box_path, env=env)

    assert result.exit_code == 0
    assert f"Options override the conservative preset: {overriding}." in result.stderr
    assert dropped not in applied_options(result, Preset.CONSERVATIVE)


def test_preset_takes_some_options_without_a_warning(invoke, make_box):
    """Two kinds of options set over a preset raise no warning.

    A value equal to the preset's changes nothing. The strategy decides which copy
    stays, not what counts as a copy, so it replaces the preset's in silence.
    """
    copy = MailFactory(date="2024-05-10", message_id="<garden@nohost.com>")
    box_path, _, _ = make_box(Maildir, [copy, copy])

    result = invoke(
        "--preset=conservative",
        "--hash-body=raw",
        "--strategy=select-matching-path",
        "--regexp=.*",
        "--action=delete-discarded",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 0
    assert "override the conservative preset" not in result.stderr
    applied = applied_options(result, Preset.CONSERVATIVE)
    assert "--hash-body raw" in applied
    assert "--strategy" not in applied
    assert "select-matching-path strategy will be applied" in result.stderr


def test_preset_thresholds_stay_on_without_its_hashing(invoke, tmp_path):
    """Replacing a hashing option of the conservative preset keeps the thresholds on.

    Under `--hash-body skip`, the hash covers the header block alone, so two mails
    with the same headers and different bodies share it. The preset turns the
    thresholds off only with its own hashing options, so here they stay on and skip
    the set.
    """
    box_path = str(tmp_path / "box")
    box = Maildir(box_path, create=True)
    headers = (
        b"Date: Mon, 05 Feb 2024 09:00:00 +0000\n"
        b"From: fig@example.com\n"
        b"To: plum@example.com\n"
        b"Subject: harvest\n"
        b"Message-ID: <harvest@example.com>\n"
        b"\n"
    )
    box.add(headers + b"Figs and plums.\n" * 100)
    box.add(headers + b"Apricots and pears, picked in the rain.\n" * 100)
    box.close()

    result = invoke(
        "--preset=conservative",
        "--hash-body=skip",
        "--action=delete-discarded",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 0
    assert "Skip set: mails are too dissimilar in size." in result.stderr
    assert metrics(result.stdout)["Deleted"] == "0"
    applied = applied_options(result, Preset.CONSERVATIVE)
    assert "--size-threshold" not in applied
    assert "--content-threshold" not in applied
    assert (
        "Options keep their defaults, because their values in the conservative "
        "preset rely on overridden options: -C/--content-threshold and "
        "-S/--size-threshold."
    ) in result.stderr


@pytest.mark.parametrize(
    ("args", "kept"),
    (
        pytest.param(("--hash-body=decoded",), False, id="hash-body"),
        # The header list and the raw headers make one choice.
        pytest.param(("--hash-header=subject",), False, id="header-list"),
        pytest.param(("--no-raw-headers",), False, id="negated-flag"),
        # The values of the preset, given by the user.
        pytest.param(("--raw-headers", "--hash-body=raw"), True, id="same-values"),
    ),
)
def test_preset_thresholds_rely_on_its_hashing(invoke, make_box, args, kept):
    """The thresholds of the conservative preset apply only with its hashing options.

    Replacing a hashing option, directly or through the option linked to it, leaves
    the thresholds at their defaults. A user value equal to the preset's keeps them.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke("--preset=conservative", *args, "--hash-only", box_path)

    assert result.exit_code == 0
    applied = applied_options(result, Preset.CONSERVATIVE)
    assert ("--size-threshold -1" in applied) is kept
    assert ("--content-threshold -1" in applied) is kept
    assert ("Options keep their defaults" in result.stderr) is not kept


def test_raw_headers_refuse_a_header_list(invoke, make_box):
    """`--raw-headers` and `--hash-header` set together contradict each other."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke("--raw-headers", "--hash-header=subject", "--hash-only", box_path)

    assert result.exit_code == 2
    assert "--raw-headers hashes every header, so -h/--hash-header has" in result.stderr


def test_conservative_preset_keeps_near_copies(invoke, make_box):
    """Only identical copies are deduplicated: a near copy is left untouched.

    The same three mails collapse into one set under the default hashing, as the
    near copy shares every hashed header and differs by a footer the thresholds
    allow. The footer sits on the body's single line: `MailFactory` indents the
    first line of a body alone, so a second line would break the mail apart.
    """
    mail = MailFactory(
        date="2024-05-10",
        message_id="<garden@nohost.com>",
        body="Plums and quinces.\n",
    )
    near_copy = MailFactory(
        date="2024-05-10",
        message_id="<garden@nohost.com>",
        body="Plums and quinces. Unsubscribe: lists.example.com\n",
    )
    box_path, box_type, _ = make_box(Maildir, [mail, mail, near_copy])

    result = invoke("--preset=conservative", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert applied_options(result, Preset.CONSERVATIVE) == (
        "--raw-headers --hash-body raw --size-threshold -1 --content-threshold -1 "
        "--strategy select-one"
    )
    # The strategy of the preset, as no copy of a set is worth more than another.
    assert "select-one strategy will be applied" in result.stderr
    check_box(box_path, box_type, content=[mail, near_copy])

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert len(Maildir(box_path, create=False)) == 1


def test_raw_headers_hash_a_mail_lacking_headers(invoke, tmp_path):
    """No minimal number of headers applies to the raw headers.

    The same mail gets no hash under the default hashing: see
    `test_mail_with_too_few_headers_is_kept`.
    """
    box_path = str(tmp_path / "box")
    box = Maildir(box_path, create=True)
    for _ in range(2):
        box.add(b"Subject: lonely mail\n\nA body.\n")
    box.close()

    result = invoke("--preset=conservative", "--action=delete-discarded", box_path)

    assert result.exit_code == 0
    assert "too few headers" not in result.stderr
    assert len(Maildir(box_path, create=False)) == 1


def test_raw_headers_hash_only_shows_every_header(invoke, make_box):
    """Under `--raw-headers`, `--hash-only` lists every header of a mail."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke("--raw-headers", "--hash-only", box_path)

    assert result.exit_code == 0
    assert "Use every header, as stored, to compute hashes." in result.stderr
    # Headers the default list leaves out.
    assert "Envelope-to" in result.stdout
    assert "Received" in result.stdout
    assert "Hash: " in result.stdout


def test_conservative_preset_parallel_run_matches_sequential(invoke, make_box):
    """The conservative preset picks the same copies in a worker process."""
    pairs = [
        MailFactory(date="2024-05-10", message_id="<a@nohost.com>"),
        MailFactory(date="2024-05-10", message_id="<b@nohost.com>"),
    ]
    box_path, _, _ = make_box(Maildir, [mail for mail in pairs for _ in range(2)])
    args = ("--preset=conservative", "--action=delete-selected", "--dry-run", box_path)

    sequential = invoke(*args)
    parallel = invoke("--jobs=2", *args)

    assert sequential.exit_code == 0
    assert parallel.exit_code == 0
    assert parallel.stdout == sequential.stdout
    assert acted_upon(parallel) == acted_upon(sequential)


def test_headers_table_rendered_only_when_logged(invoke, make_box, monkeypatch):
    """The canonical-headers table is not built at the default verbosity.

    Rendering it goes through `tabulate` and costs more than the hash itself, yet any
    level above debug discards it.
    """
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


@pytest.mark.parametrize(
    ("args", "message"),
    (
        # The space (ASCII 32) falls below the RFC-5322 printable range.
        pytest.param(
            ("--hash-header", "bad header"),
            "invalid header ID: 'bad header'.",
            id="header-with-space",
        ),
        pytest.param(
            ("--hash-header", ""), "invalid header ID: ''.", id="empty-header"
        ),
        pytest.param(
            ("--strategy=select-matching-path", "--regexp=["),
            "invalid regular expression",
            id="uncompilable-regexp",
        ),
    ),
)
def test_invalid_option_value_rejected(invoke, make_box, args, message):
    """An option value that cannot work is refused at parse time."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke(*args, box_path)

    assert result.exit_code == 2
    assert message in result.stderr


def test_duplicate_source_rejected(invoke, make_box):
    """The same mail source given twice is refused.

    The source path is the key that ties a mail back to its origin.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    result = invoke(
        "--strategy=select-one", "--action=delete-discarded", box_path, box_path
    )

    assert result.exit_code == 1
    assert_one_line_error(result, f"Error: {Path(box_path).resolve()} already added.")


def test_hash_only_warns_about_ignored_options(invoke, make_box):
    """--hash-only ignores the options of the selection and action steps it skips.

    Any of them the user set is reported.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory(message_id="<h@nohost.com>")])

    result = invoke("--hash-only", "--strategy=select-one", box_path)

    assert result.exit_code == 0
    assert "ignored in -H/--hash-only mode" in result.stderr
    assert "--strategy" in result.stderr


def test_main_entrypoint_reports_version(monkeypatch, capsys):
    """The `main()` indirection runs the CLI end to end: `--version` exits cleanly."""
    monkeypatch.setattr(sys, "argv", ["mdedup", "--version"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert "mdedup" in capsys.readouterr().out


@pytest.mark.parametrize(
    "enter_worker",
    [
        # A spawn or forkserver worker, importing the main module of its parent.
        pytest.param(
            lambda patch: patch.setattr(
                multiprocessing.current_process(), "_inheriting", True, raising=False
            ),
            id="bootstrap",
        ),
        # A Nuitka worker, which runs the launcher before any bootstrap.
        pytest.param(
            lambda patch: patch.setattr(
                builtins, "__nuitka_original_args", ["mdedup"], raising=False
            ),
            id="nuitka",
        ),
    ],
)
def test_main_refuses_to_run_in_a_worker(monkeypatch, enter_worker):
    """`main()` exits before it imports the CLI, in both states a worker reaches it."""
    enter_worker(monkeypatch)
    monkeypatch.setattr(
        "mail_deduplicate.cli.mdedup", lambda: pytest.fail("The CLI ran in a worker.")
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == WORKER_RERUN_ERROR


UNGUARDED_LAUNCHER = """\
import multiprocessing
import sys

import mail_deduplicate.__main__ as user_main

# Each spawn worker imports this file again, which calls main() in it.
multiprocessing.set_start_method("spawn", force=True)
sys.exit(user_main.main())
"""
"""A launcher shaped like the one Nuitka writes for `--main-entry-point`, with no
`__name__ == "__main__"` guard around its call."""


def test_unguarded_launcher_stops_in_each_worker(tmp_path):
    """A launcher calling `main()` on import stops in each `--jobs` worker.

    It stops before the CLI there opens a box. The parent then fails on its broken
    pool.

    The run cannot multiply processes, guard or not: CPython refuses to start a
    process from a worker that is still importing its parent's main module.
    """
    launcher = tmp_path / "mdedup.py"
    launcher.write_text(UNGUARDED_LAUNCHER, encoding="UTF-8")
    box = Path(__file__).parent / "fixtures" / "eml-box"

    result = subprocess.run(
        (sys.executable, str(launcher), "--jobs=2", "--hash-only", str(box)),
        capture_output=True,
        # The run prints characters that a legacy Windows code page cannot encode.
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        encoding="UTF-8",
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    # Sandboxes, containers and a host out of semaphores refuse to start processes,
    # and the run then hashes in the parent, with no worker to test.
    if "Hash in this process instead." in output:
        pytest.skip("This host refused to start the worker processes.")

    assert result.returncode != 0
    assert WORKER_RERUN_ERROR in output
    # Only the parent opened the box: no worker got as far as the CLI.
    assert output.count("Opening ") == 1
    assert "bootstrapping phase" not in output
