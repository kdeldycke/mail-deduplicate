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

"""Capture the `mdedup` invocations the readme illustrates, as SVG terminal windows.

Each capture is a real run of the working tree's CLI over a small playground of
duplicated mails, drawn by `click-extra screenshot` into `docs/assets/`. The readme
references the results by raw GitHub URL, which is why they are SVG rather than HTML:
a readme rendered on GitHub or PyPI strips inline markup, so a picture is the only
rendering those two surfaces will show.

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
subject is what the pipeline reports about them. The playground below is rebuilt
from scratch on every capture, from the same seven mails the tutorial builds, so
a recapture on one machine is byte-identical to the previous one and `git diff`
stays empty until the CLI itself changes what it prints.
```

```{note}
The playground lives at a fixed path rather than in a `tempfile.mkdtemp()`
directory, because `mdedup` prints the resolved absolute path of every source and
of every mail it acts on. A scratch directory would stamp each capture with a
`/var/folders/...` prefix no reader can parse, and a new one on every run.
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
from pathlib import Path

from click_extra.layout import cell_width
from click_extra.screenshot import AUTO_WRAP_MARKER, resolve_wrap_marker

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
so every extra character shrinks the text. A capture whose output needs another
width states its own in `extra`, which then replaces this one rather than
joining it.
"""

WRAP_MARKER = AUTO_WRAP_MARKER
"""Marker closing each row a line wider than {data}`COLUMNS` folds at.

`mdedup` prints a few lines no terminal width holds, like the list of hashed
headers. Folded silently, such a line reads as a typo where the fold lands
mid-word, so every capture marks its folds.

The marker takes the last cell of the row it closes, so it shortens every row's
budget by one, the prompt's included: see {func}`prompt_budget`.
"""

PROMPT_SIGIL = "$ "
"""Characters the `macos` preset draws ahead of the command line, per
{data}`~click_extra.screenshot_presets.MACOS_PRESET`.

Counted against {data}`COLUMNS` beside the command line itself, so the row the
prompt takes is measured whole.
"""

SOURCES = ("2024.mbox", "2025.mbox")
"""The two playground boxes every capture runs on.

Named for the year alone rather than `archive-2024.mbox`: the command lines below
have to fit {data}`COLUMNS` on one row, and the boxes are rebuilt on every capture
anyway, so a shorter name costs the picture nothing.
"""

MERGE_ARGS = ("--strategy", "select-matching-path", "--regexp", "2024")
"""Options every capture shares, beyond the action and the sources.

No `--jobs`: `mdedup` already defaults it to `1`, and pinning it here would spend
characters of the command line on the value it resolves to anyway.

`select-matching-path` rather than the `select-one` the readme names for
byte-identical copies: `select-one` keeps a copy at random, so two recaptures of
the same command would disagree on which copy survived, and the picture would
change where the CLI did not. A path criterion is the one strategy family that
splits copies a backup left identical, and it is fully determined by the mails
themselves, as `docs/performance.md` details.
"""

CAPTURES = (
    (
        "mdedup-header-cli",
        (*MERGE_ARGS, "--export", "merged.mbox", *SOURCES),
        "Merging two overlapping archives",
        # The readme's header picture stops where the report begins: the five
        # steps' trail, closing on the action's own count, without the two report
        # tables the full capture below shows. --head counts output lines, the
        # prompt excluded: 32 keeps through the blank line after the trail.
        ("--merge-stderr", "--head", "32"),
    ),
    (
        "mdedup-run-cli",
        (*MERGE_ARGS, "--export", "merged.mbox", *SOURCES),
        "A whole run, report included",
        # Every line the run prints: the five steps, the action trail and both
        # report tables. Nothing is cut, since the report is what a first-time
        # reader needs to recognize on their own run.
        ("--merge-stderr",),
    ),
    (
        "mdedup-dry-run-cli",
        (*MERGE_ARGS, "--action", "delete-discarded", "--dry-run", *SOURCES),
        "Rehearsing a destructive action",
        ("--merge-stderr",),
    ),
)
"""The captures, as `(stem, mdedup arguments, window caption, extra options)` tuples.

The stems are the file names the readme links, so renaming one breaks the readme
and the two must move together.
"""


def make_mail(subject: str, date: str, msg_id: str, body: str) -> EmailMessage:
    """Build one mail of the playground, with the headers `mdedup` hashes by default."""
    mail = EmailMessage()
    mail["From"] = "news@example.com"
    mail["To"] = "me@example.com"
    mail["Subject"] = subject
    mail["Date"] = date
    mail["Message-ID"] = msg_id
    mail.set_content(body)
    return mail


def build_playground() -> None:
    """Recreate the two overlapping `mbox` archives every capture runs on.

    The same seven mails the tutorial's playground holds: two present in both
    archives, which are the duplicates, and three unique to one of them. One
    unique mail shares its `Weekly digest` subject with a shared mail, on
    purpose: a matcher keying on subjects alone would wrongly collapse them, and
    the report shows it did not.
    """
    if PLAYGROUND.is_symlink():
        sys.exit(f"{PLAYGROUND} is a symlink: remove it by hand and run again.")
    if PLAYGROUND.exists():
        shutil.rmtree(PLAYGROUND)
    PLAYGROUND.mkdir(parents=True)

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
    only_2024 = [
        make_mail(
            "Invoice January",
            "Wed, 31 Jan 2024 12:00:00 +0000",
            "<invoice-2024-01@example.com>",
            "Your invoice is attached.\n",
        ),
    ]
    only_2025 = [
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
    ]
    for filename, mails in (
        (SOURCES[0], shared + only_2024),
        (SOURCES[1], shared + only_2025),
    ):
        box = mailbox.mbox(PLAYGROUND / filename)
        for mail in mails:
            box.add(mailbox.mboxMessage(mail))
        box.flush()
        box.close()


def prompt_budget(columns: int = COLUMNS) -> int:
    """Cells a command line can take before it folds onto a second row.

    :param columns: width the capture is drawn at.
    """
    return columns - cell_width(resolve_wrap_marker(WRAP_MARKER))


def check_column_budget(args: tuple[str, ...]) -> int:
    """Fail unless the command line of a capture fits its window on one row.

    Returns the row's length in characters.

    A wrapped prompt reads as two commands, and the second one starts mid-option,
    so the picture teaches an invocation nobody can type. Nothing in the renderer
    refuses an over-long one, hence this guard: it runs before the capture, and
    names the row that overflows.

    :param args: arguments handed to `mdedup`, as the drawn prompt shows them.
    """
    row = PROMPT_SIGIL + shlex.join(("mdedup", *args))
    if cell_width(row) > prompt_budget():
        sys.exit(
            f"The command line of {row!r} measures {cell_width(row)} cells, past "
            f"the {prompt_budget()} COLUMNS leaves beside the wrap marker: it would "
            "wrap onto a second row. Shorten the invocation or widen COLUMNS."
        )
    return cell_width(row)


def capture(
    stem: str,
    args: tuple[str, ...],
    title: str,
    extra: tuple[str, ...],
    mdedup: str,
) -> Path:
    """Run one `mdedup` invocation and draw its output into `docs/assets/{stem}.svg`.

    Returns the path written.

    :param stem: file name of the capture, without its extension.
    :param args: arguments handed to `mdedup`.
    :param title: caption drawn in the window's title bar.
    :param extra: further options for the `screenshot` command itself.
    :param mdedup: the `mdedup` executable to run.
    """
    check_column_budget(args)
    build_playground()
    target = ASSETS_DIR / f"{stem}.svg"
    subprocess.run(
        (
            sys.executable,
            "-m",
            "click_extra",
            "screenshot",
            "--output",
            str(target),
            # A repeated --columns keeps its *first* value, so the default is
            # withheld when a capture states a width of its own. Emitting both
            # pinned every capture to COLUMNS, override or not.
            *(() if "--columns" in extra else ("--columns", str(COLUMNS))),
            "--preset",
            PRESET,
            "--title",
            title,
            # The captured binary is reached by path, so that path would otherwise
            # be the command line drawn above the output. Draw what a reader types.
            # Quoted argument by argument: the drawn line is re-split on spaces
            # before it is rendered, so joining a spaced argument back with plain
            # spaces draws a command line that no longer runs.
            "--prompt",
            shlex.join(("mdedup", *args)),
            # The renderer credits itself in the margin by default. The readme
            # embeds these small enough that the line is unreadable, and the
            # picture is this project's own CLI output, so nothing is owed.
            "--watermark",
            "",
            "--wrap-marker",
            WRAP_MARKER,
            *extra,
            "--",
            mdedup,
            *args,
        ),
        check=True,
        cwd=PLAYGROUND,
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
        choices=[stem for stem, _, _, _ in CAPTURES],
        help="Capture this file only. Repeat to name several.",
    )
    args = parser.parse_args()

    for stem, mdedup_args, title, extra in CAPTURES:
        if args.only and stem not in args.only:
            continue
        target = capture(stem, mdedup_args, title, extra, args.mdedup)
        print(f"Wrote {target.relative_to(PROJECT_ROOT)}")
