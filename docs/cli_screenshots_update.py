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

"""Capture the `mdedup` invocations the readme and the docs illustrate, as SVG.

Each capture is a real run of the working tree's CLI over a small playground of
mails built for it, drawn by `click-extra screenshot` into `docs/assets/`. The
readme references the results by raw GitHub URL, which is why they are SVG rather
than HTML: a readme rendered on GitHub or PyPI strips inline markup, so a picture
is the only rendering those two surfaces will show. The docs pages embed the same
files by relative path.

```{caution}
Run by hand, and never from CI or a docs build. A capture pictures the CLI the
working tree holds at that moment, plus the logical CPU count of the host, so a
runner would rewrite every asset on every push. That is the same rule
meta-package-manager's `docs/cli_screenshots_update.py` follows, for the same
reason: the committed artifact keeps the build hermetic.
```

```{note}
The payload is deliberately held still, the opposite of meta-package-manager's
captures, whose live inventory is the subject. Here the mails are noise: the
subject is what the pipeline reports about them. Each playground is rebuilt from
scratch on every capture, so a recapture on one machine is byte-identical to the
previous one and `git diff` stays empty until the CLI changes what it prints.

Three captures are exceptions. The two recordings of {data}`OPT_IN_CAPTURES`
carry the timing of the run they recorded. The bug report names the version and
the commit it was drawn from, so it changes with every commit recaptured.
```

```{note}
The playground lives at a fixed path rather than in a `tempfile.mkdtemp()`
directory, because `mdedup` prints the resolved absolute path of every source and
of every mail it acts on. A scratch directory would stamp each capture with a
`/var/folders/...` prefix no reader can parse, and a new one on every run.

That is also why these captures are not drawn by the `:screenshot:` option of the
tutorial's `click:run` blocks: those run in a scratch directory, and on a docs
build host whose temporary directory differs from a workstation's.
```

Run it from the repository root, so `mdedup` resolves to the working tree's own
console script:

```shell-session
$ uv run -- python docs/cli_screenshots_update.py
```
"""

from __future__ import annotations

import argparse
import mailbox
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from functools import partial
from pathlib import Path
from typing import NamedTuple

from click_extra.layout import cell_width
from click_extra.screenshot import AUTO_WRAP_MARKER, resolve_wrap_marker

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable

PROJECT_ROOT = Path(__file__).parent.parent
"""Repository root, which the captures write their SVGs into.

The runs themselves happen in {data}`PLAYGROUND`, so that the paths they print
stay short."""

ASSETS_DIR = PROJECT_ROOT / "docs" / "assets"
"""Directory the captures are written to, beside the brand artwork."""

PLAYGROUND = (
    Path("/tmp/mdedup-playground")
    if os.name == "posix"
    else Path(tempfile.gettempdir()) / "mdedup-playground"
)
"""Fixed directory the captures run in, holding the playground boxes.

`mdedup` resolves every source to an absolute path before printing it, so the
directory name ends up in the picture: keep it short, stable and free of any
per-user component.
"""

PRESET = "macos"
"""Terminal chrome every capture is drawn as.

One preset for the whole set, so the readme reads as one machine rather than a
gallery of window managers.
"""

COLUMNS = 112
"""Width every capture wraps its output to.

The floor is the longest command line a capture draws, plus the cell
{data}`WRAP_MARKER` takes: the invocation sits on one row, and a wider one wraps
onto a second row, which reads as a different command. {func}`check_column_budget`
holds every capture to that, and the script fails before drawing one that does not
fit.

The ceiling is legibility: the readme embeds these scaled down to its own column,
so every extra character shrinks the text.
"""

ROWS = 32
"""Height of the terminal a recorded capture runs in.

Tall enough for the two report tables to scroll past and settle, so the last
frame of a recording shows the end of the run.
"""

WRAP_MARKER = AUTO_WRAP_MARKER
"""Marker closing each row a line wider than {data}`COLUMNS` folds at.

`mdedup` prints a few lines no terminal width holds, like the list of hashed
headers. Folded silently, such a line reads as a typo where the fold lands
mid-word, so every still capture marks its folds. A recording has no marker: its
pseudo-terminal folds its own lines.

The marker takes the last cell of the row it closes, so it shortens every row's
budget by one, the prompt's included: see {func}`prompt_budget`.
"""

PROMPT_SIGIL = "$ "
"""Characters the `macos` preset draws ahead of the command line, per
{data}`~click_extra.screenshot_presets.MACOS_PRESET`.

Counted against {data}`COLUMNS` beside the command line itself, so the row the
prompt takes is measured whole.
"""

AGENT_VARIABLES = (
    "AI_AGENT",
    "CLAUDECODE",
    "CLINE_ACTIVE",
    "CODEX_CI",
    "COPILOT_CLI",
    "CURSOR_AGENT",
    "GEMINI_CLI",
    "PI_CODING_AGENT",
)
"""Environment variables `extra-platforms` reads to detect an AI agent.

The bug report adds a line asking an agent to show the report to its user. A
capture run from inside an agent would picture that line, which no person running
`mdedup` sees, so the captures run without them: see {func}`capture_environment`.
"""

INJECTED_FAILURE = """\
import sys

from mail_deduplicate.__main__ import main
from mail_deduplicate.mail import DedupMailMixin

original = DedupMailMixin.hash_key


def hash_key(self):
    if self.get("Message-ID") == "<reset-2025-03-11@example.com>":
        raise UnicodeEncodeError("ascii", "à bientôt", 0, 1, "ordinal not in range(128)")
    return original(self)


DedupMailMixin.hash_key = hash_key
sys.argv[0] = "mdedup"
main()
"""
"""Python source running `mdedup` with an error forced on one mail.

The bug report only shows up on an error `mdedup` has no rule for, and every such
error found so far is fixed. So the capture makes one: hashing the mail with the
`Password reset` subject raises the `UnicodeEncodeError` a few real reports
named. Everything after the error is the real code path. The forced frame shows
up in the report's traceback as `__main__`, so the picture does not hide it.
"""


def make_mail(
    subject: str,
    date: str,
    msg_id: str,
    body: str,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> EmailMessage:
    """Build one mail of a playground, with the headers `mdedup` hashes by default."""
    mail = EmailMessage()
    mail["From"] = "news@example.com"
    mail["To"] = "me@example.com"
    mail["Subject"] = subject
    mail["Date"] = date
    mail["Message-ID"] = msg_id
    for name, value in extra_headers:
        mail[name] = value
    mail.set_content(body)
    return mail


def write_mbox(filename: str, mails: list[EmailMessage]) -> None:
    """Write `mails` to a new `mbox` box in {data}`PLAYGROUND`."""
    box = mailbox.mbox(PLAYGROUND / filename)
    for mail in mails:
        box.add(mailbox.mboxMessage(mail))
    box.flush()
    box.close()


def archives_playground() -> None:
    """Two overlapping `mbox` archives: `2024.mbox` and `2025.mbox`.

    The same seven mails the tutorial's playground holds: two present in both
    archives, which are the duplicates, and three unique to one of them. One
    unique mail shares its `Weekly digest` subject with a shared mail, on
    purpose: a matcher keying on subjects alone would wrongly collapse them, and
    the report shows it did not.
    """
    shared = [
        make_mail(
            "Weekly digest",
            "Mon, 05 Feb 2024 09:00:00 +0000",
            "<digest-2024-02-05@example.com>",
            "This week's news.\n",
        ),
        make_mail(
            "Server maintenance window",
            "Wed, 03 Apr 2024 17:30:00 +0000",
            "<maintenance-2024-04-03@example.com>",
            "The server will be down on Friday.\n",
        ),
    ]
    write_mbox(
        "2024.mbox",
        [
            *shared,
            make_mail(
                "Invoice January",
                "Wed, 31 Jan 2024 12:00:00 +0000",
                "<invoice-2024-01@example.com>",
                "Your invoice is attached.\n",
            ),
        ],
    )
    write_mbox(
        "2025.mbox",
        [
            *shared,
            make_mail(
                "Weekly digest",
                "Mon, 03 Feb 2025 09:00:00 +0000",
                "<digest-2025-02-03@example.com>",
                "This week's news, a year later.\n",
            ),
            make_mail(
                "Password reset",
                "Tue, 11 Mar 2025 08:15:00 +0000",
                "<reset-2025-03-11@example.com>",
                "Click the link to reset your password.\n",
            ),
        ],
    )


def lookalikes_playground() -> None:
    """Two boxes, `new.mbox` and `old.mbox`, holding one true pair and one false pair.

    The `Sunday menu` mail is in both boxes, byte for byte: a real duplicate. The
    two `Weekly notes` mails share every hashed header, `Message-ID` included, the
    way a client reusing an ID makes them, but one holds a soup recipe and the
    other a weather log. Their sizes are close enough to pass the size threshold,
    so only the content threshold can tell them apart.
    """
    menu = partial(
        make_mail,
        "Sunday menu",
        "Sun, 07 Apr 2024 09:00:00 +0000",
        "<menu-2024-04-07@example.com>",
        "Leek soup, then a plum tart.\n",
    )
    notes = partial(
        make_mail,
        "Weekly notes",
        "Mon, 08 Apr 2024 07:30:00 +0000",
        "<notes@example.com>",
    )
    recipe = "".join(
        f"Step {n}: simmer the leeks and potatoes for {n + 4} minutes.\n"
        for n in range(1, 13)
    )
    weather = "".join(
        f"Day {n}: light rain over Lisbon, {14 + n} degrees by noon.\n"
        for n in range(1, 13)
    )
    write_mbox("new.mbox", [menu(), notes(body=recipe)])
    write_mbox("old.mbox", [menu(), notes(body=weather)])


def mailing_list_playground() -> None:
    """One mail kept twice: as sent, and as a mailing list delivered it back.

    `sent.mbox` holds the mail as it left. `garden-club.mbox` holds the copy the
    list sent back, with a `[garden-club]` subject prefix, the list's own headers
    and an unsubscribe footer. None of those changes reach the hash.
    """
    body = "This week's harvest: plums and quinces.\n"
    date = "Mon, 05 Feb 2024 09:00:00 +0000"
    msg_id = "<digest-2024-02-05@example.com>"
    write_mbox("sent.mbox", [make_mail("Weekly digest", date, msg_id, body)])
    write_mbox(
        "garden-club.mbox",
        [
            make_mail(
                "[garden-club] Weekly digest",
                date,
                msg_id,
                body + "\n--\nUnsubscribe: https://lists.example.com/garden-club\n",
                extra_headers=(
                    ("List-Id", "<garden-club.lists.example.com>"),
                    ("Precedence", "list"),
                    ("X-BeenThere", "garden-club@lists.example.com"),
                ),
            ),
        ],
    )


ARCHIVE_SIZE = 20_000
"""Number of mails in the maildir the cache recordings run on.

Measured on the workstation the recordings were first drawn on: 5.9 seconds for
an uncached run with `--hash-body normalized`, and 0.8 seconds for the cached one.
At 4,000 mails the two runs took 1.4 and 0.4 seconds, too brief for a progress
bar to read.
"""

FRUITS = ("apricot", "banana", "cherry", "damson", "fig", "guava", "kiwi", "lemon")
"""Senders of the generated archive, one per orchard."""

CACHE_PATH = "cache.db"
"""Hash cache the recordings use, inside {data}`PLAYGROUND`.

Pointed at with `--cache-path` rather than enabled with `--cache`, so a recording
neither reads nor fills the cache of the user running the script.
"""

ARCHIVE_ARGS = (
    "--hash-body",
    "normalized",
    "--cache-path",
    CACHE_PATH,
    "--strategy",
    "select-one",
    "--action",
    "delete-discarded",
    "Archive",
)
"""The run both cache recordings picture.

`--hash-body normalized` makes hashing read every body, which is the work the
cache saves. A few mails are filed twice, so the trail stays short. No
`--dry-run`: the archive is rebuilt for each recording, and the flag would push
the command line past {data}`COLUMNS`.
"""


def archive_playground() -> None:
    """A `maildir` of {data}`ARCHIVE_SIZE` mails, four of them filed twice."""
    box = mailbox.Maildir(PLAYGROUND / "Archive", create=True)
    for number in range(ARCHIVE_SIZE):
        fruit = FRUITS[number % len(FRUITS)]
        mail = make_mail(
            f"Harvest report {number}",
            f"Mon, {1 + number % 28:02d} Sep 2025 "
            f"{number % 24:02d}:{number % 60:02d}:00 +0000",
            f"<harvest-{number}@orchard.example>",
            f"The {fruit} trees gave a fine crop this week.\n" * 40,
        )
        box.add(mailbox.MaildirMessage(mail))
        if number % (ARCHIVE_SIZE // 4) == 7:
            box.add(mailbox.MaildirMessage(mail))
    box.close()


def warm_archive_playground() -> None:
    """The archive of {func}`archive_playground`, with its hash cache filled.

    Filled by a dry run of the very run the recording then repeats, so every entry
    matches and the duplicates are still there to delete.
    """
    archive_playground()
    subprocess.run(
        ("mdedup", "--dry-run", *ARCHIVE_ARGS),
        check=True,
        cwd=PLAYGROUND,
        capture_output=True,
        env=capture_environment(),
    )


class Capture(NamedTuple):
    """One picture, and how to draw it."""

    stem: str
    """File name of the capture, without its extension.

    The readme and the docs link the file by this name, so renaming one breaks
    them and the two must move together.
    """

    args: tuple[str, ...]
    """Arguments handed to `mdedup`, as the drawn prompt shows them."""

    title: str
    """Caption drawn in the window's title bar."""

    playground: Callable[[], None]
    """Builds the boxes the run reads, in an empty {data}`PLAYGROUND`."""

    extra: tuple[str, ...] = ()
    """Further options for the `screenshot` command itself."""

    recorded: bool = False
    """Record an animation of the run rather than draw its final output.

    A recording carries the timing of the run it recorded, so it differs on every
    recapture: it is in {data}`OPT_IN_CAPTURES`.
    """

    injected: bool = False
    """Run {data}`INJECTED_FAILURE` in place of `mdedup`.

    The prompt still shows the `mdedup` command, which a reader cannot reproduce
    on their own boxes. The page embedding such a capture says so instead of
    showing the command.
    """


MERGE_ARGS = ("--strategy", "select-matching-path", "--regexp", "2024")
"""Options the captures of {func}`archives_playground` share.

`select-matching-path` rather than the `select-one` the readme names for
byte-identical copies: `select-one` keeps a copy at random, so two recaptures of
the same command would disagree on which copy survived, and the picture would
change where the CLI did not. A path criterion is the one strategy family that
splits copies a backup left identical, and it is fully determined by the mails
themselves, as `docs/performance.md` details.
"""

SOURCES = ("2024.mbox", "2025.mbox")
"""The two boxes of {func}`archives_playground`.

Named for the year alone rather than `archive-2024.mbox`: the command lines have
to fit {data}`COLUMNS` on one row.
"""

LOOKALIKE_ARGS = (
    "--strategy",
    "discard-matching-path",
    "--regexp",
    "old",
    "--action",
    "delete-discarded",
    "--dry-run",
    "new.mbox",
    "old.mbox",
)
"""The run both captures of {func}`lookalikes_playground` picture.

A path strategy, for the reason {data}`MERGE_ARGS` gives, and a dry run: the
picture is about what `mdedup` decides, not about a box changing.
"""

CAPTURES = (
    Capture(
        "mdedup-header-cli",
        (*MERGE_ARGS, "--export", "merged.mbox", *SOURCES),
        "Merging two overlapping archives",
        archives_playground,
        # The readme's header picture stops where the report begins: the five
        # steps' trail, closing on the action's own count, without the two report
        # tables the full capture below shows. --head counts output lines, the
        # prompt excluded: 27 keeps through the blank line after the trail.
        ("--merge-stderr", "--head", "27"),
    ),
    Capture(
        "mdedup-run-cli",
        (*MERGE_ARGS, "--export", "merged.mbox", *SOURCES),
        "A whole run, report included",
        archives_playground,
        # Every line the run prints: the five steps, the action trail and both
        # report tables. Nothing is cut, since the report is what a first-time
        # reader needs to recognize on their own run.
        ("--merge-stderr",),
    ),
    Capture(
        "mdedup-dry-run-cli",
        (*MERGE_ARGS, "--action", "delete-discarded", "--dry-run", *SOURCES),
        "Rehearsing a destructive action",
        archives_playground,
        ("--merge-stderr",),
    ),
    Capture(
        "mdedup-safeguard-cli",
        LOOKALIKE_ARGS,
        "Two mails that only look alike",
        lookalikes_playground,
        # The steps through the action trail, then the set statistics, where the
        # skipped set is counted. The mail statistics between them repeat what the
        # trail already says.
        ("--merge-stderr", "--head", "24", "--tail", "26"),
    ),
    Capture(
        "mdedup-show-diff-cli",
        (
            "--show-diff",
            "--strategy",
            "select-one",
            "--export",
            "merged.mbox",
            "new.mbox",
            "old.mbox",
        ),
        "What tells two lookalikes apart",
        lookalikes_playground,
        # Through the diff and the verdict it leads to, before any action: the
        # picture stops ahead of the copy `select-one` picks at random, so a
        # recapture draws the same picture.
        ("--merge-stderr", "--head", "44"),
    ),
    Capture(
        "mdedup-hash-only-cli",
        ("--hash-only", "sent.mbox", "garden-club.mbox"),
        "A mail, and its copy a mailing list sent back",
        mailing_list_playground,
        # The two canonical header tables and their hashes, without the loading
        # steps above them.
        ("--merge-stderr", "--tail", "25"),
    ),
    Capture(
        "mdedup-bug-report-cli",
        (*MERGE_ARGS, "--export", "merged.mbox", *SOURCES),
        "The bug report of an unexpected error",
        archives_playground,
        # The run up to the mail it set aside, then the report closing it. The
        # statistics between them hold one more row, `Failed`, at 1.
        ("--merge-stderr", "--head", "13", "--tail", "28"),
        injected=True,
    ),
    Capture(
        "mdedup-cache-cold-cli",
        ARCHIVE_ARGS,
        "A first run, filling the hash cache",
        archive_playground,
        # The timeout guards against a run stuck on a lock, not an expected
        # duration: the run takes seconds. The hold scales with the last screen's
        # line count by default, which reads as 22 seconds for a full report.
        ("--rows", str(ROWS), "--hold", "5", "--timeout", "300"),
        recorded=True,
    ),
    Capture(
        "mdedup-cache-warm-cli",
        ARCHIVE_ARGS,
        "The same run, reading its hashes back",
        warm_archive_playground,
        ("--rows", str(ROWS), "--hold", "5", "--timeout", "300"),
        recorded=True,
    ),
)
"""Every capture, in the order the script draws them."""

OPT_IN_CAPTURES = frozenset(capture.stem for capture in CAPTURES if capture.recorded)
"""Captures a wholesale run skips, because no two recaptures are alike.

A recording carries the timing of the run it recorded, so redrawing it rewrites
the file even when the CLI did not change. Each also builds a maildir of
{data}`ARCHIVE_SIZE` mails, which takes about half a minute. Naming one in
`--only` is what draws it.
"""


def capture_environment() -> dict[str, str]:
    """The environment every capture runs in: this one, minus {data}`AGENT_VARIABLES`."""
    return {
        name: value for name, value in os.environ.items() if name not in AGENT_VARIABLES
    }


def prompt_budget(capture: Capture, columns: int = COLUMNS) -> int:
    """Cells the command line of `capture` can take before it folds.

    A still capture closes each folded row on {data}`WRAP_MARKER`, which takes a
    cell. A recording draws no marker.

    :param capture: the capture whose prompt is measured.
    :param columns: width the capture is drawn at.
    """
    if capture.recorded:
        return columns
    return columns - cell_width(resolve_wrap_marker(WRAP_MARKER))


def check_column_budget(capture: Capture) -> int:
    """Fail unless the command line of a capture fits its window on one row.

    Returns the row's length in cells.

    A wrapped prompt reads as two commands, and the second one starts mid-option,
    so the picture teaches an invocation nobody can type. Nothing in the renderer
    refuses an over-long one, hence this guard: it runs before the capture, and
    names the row that overflows.

    :param capture: the capture whose prompt is measured.
    """
    row = PROMPT_SIGIL + shlex.join(("mdedup", *capture.args))
    budget = prompt_budget(capture)
    if cell_width(row) > budget:
        sys.exit(
            f"The command line of {row!r} measures {cell_width(row)} cells, past "
            f"the {budget} its window leaves: it would wrap onto a second row. "
            "Shorten the invocation or widen COLUMNS."
        )
    return cell_width(row)


def reset_playground() -> None:
    """Empty {data}`PLAYGROUND`, refusing to follow a symlink out of it."""
    if PLAYGROUND.is_symlink():
        sys.exit(f"{PLAYGROUND} is a symlink: remove it by hand and run again.")
    if PLAYGROUND.exists():
        shutil.rmtree(PLAYGROUND)
    PLAYGROUND.mkdir(parents=True)


def capture(entry: Capture, mdedup: str) -> Path:
    """Run one capture and draw it into `docs/assets/{stem}.svg`.

    Returns the path written.

    :param entry: the capture to draw.
    :param mdedup: the `mdedup` executable to run.
    """
    check_column_budget(entry)
    reset_playground()
    entry.playground()
    target = ASSETS_DIR / f"{entry.stem}.svg"
    command = (
        (sys.executable, "-c", INJECTED_FAILURE, *entry.args)
        if entry.injected
        else (mdedup, *entry.args)
    )
    subprocess.run(
        (
            sys.executable,
            "-m",
            "click_extra",
            "screenshot",
            "--output",
            str(target),
            "--columns",
            str(COLUMNS),
            "--preset",
            PRESET,
            "--title",
            entry.title,
            # The captured binary is reached by path, so that path would otherwise
            # be the command line drawn above the output. Draw what a reader types.
            # Quoted argument by argument: the drawn line is re-split on spaces
            # before it is rendered, so joining a spaced argument back with plain
            # spaces draws a command line that no longer runs.
            "--prompt",
            shlex.join(("mdedup", *entry.args)),
            # The renderer credits itself in the margin by default. The readme
            # embeds these small enough that the line is unreadable, and the
            # picture is this project's own CLI output, so nothing is owed.
            "--watermark",
            "",
            *(("--record",) if entry.recorded else ("--wrap-marker", WRAP_MARKER)),
            *entry.extra,
            "--",
            *command,
        ),
        check=True,
        cwd=PLAYGROUND,
        env=capture_environment(),
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mdedup",
        default="mdedup",
        help="The mdedup executable to capture. Defaults to the one on PATH.",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=[entry.stem for entry in CAPTURES],
        help="Capture this file only. Repeat to name several.",
    )
    args = parser.parse_args()

    for entry in CAPTURES:
        if entry.stem in OPT_IN_CAPTURES:
            if not args.only or entry.stem not in args.only:
                continue
        elif args.only and entry.stem not in args.only:
            continue
        target = capture(entry, args.mdedup)
        print(f"Wrote {target.relative_to(PROJECT_ROOT)}")
