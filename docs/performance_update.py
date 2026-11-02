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

"""Time `mdedup` for the figures of `docs/performance.md`, in one interleaved batch.

The script writes a synthetic maildir of {data}`MAILS` mails of about 4 KB, one
fifth of them exact copies of another, then runs every configuration of
{data}`CONFIGS` {data}`SAMPLES` times. Each pass runs the configurations in an
order rotated by one, so no configuration always runs first. It prints the median
of each step per configuration, then the shares and ratios the page states.

```{caution}
Run by hand, and never from CI or a docs build. The figures describe the machine
they are measured on, and only mean something against each other. A busy machine
skews them: check the load before a batch, and stop anything heavy.
```

```{note}
Each run starts on a fresh copy of the pristine corpus, so a `delete-discarded` run
always finds the same mails. On macOS, the copy is an APFS clone, which writes no
data: the mails of each run are then out of memory, like a mailbox untouched since
the last boot. A copy that writes the data instead leaves it in the file cache of
the system, and a cached run then finds its mails in memory. That is why the
published figures come from macOS, where a cached run reads its mails from disk.
```

```{note}
Step times come from the step headings `mdedup` prints, and the mails a run reads
again from the dehydration hook. Both are patched in the process that runs
`mdedup`, which is this script started again with `--harness`.
```

Run it from the repository root, outside any sandbox that refuses to start worker
processes, as the `--jobs` runs need them:

```shell-session
$ uv run -- python docs/performance_update.py
```
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import pty
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

from mail_deduplicate import cli
from mail_deduplicate.deduplicate import Deduplicate
from mail_deduplicate.mail import DedupMailMixin

SCRIPT = Path(__file__).resolve()
"""This script, started again with `--harness` for each run, from another folder."""

MAILS = 20_000
"""Number of mails in the corpus."""

COPIES = MAILS // 5
"""Number of mails that are an exact copy of another one."""

SAMPLES = 10
"""Runs of each configuration. The page reports the median."""

TIMEOUT = 300
"""Seconds after which a single run counts as hung."""

WORKDIR = Path(tempfile.gettempdir()) / "mdedup-performance"
"""Directory holding the pristine corpus, the run copy and the results."""

WORDS = (
    "apple",
    "apricot",
    "banana",
    "cherry",
    "damson",
    "fig",
    "grape",
    "guava",
    "kiwi",
    "lemon",
    "lime",
    "mango",
    "melon",
    "orange",
    "peach",
    "pear",
    "plum",
    "quince",
    "rain",
    "sun",
    "wind",
    "frost",
    "cloud",
    "storm",
    "breeze",
    "mist",
    "hail",
    "drizzle",
    "thunder",
    "harvest",
    "orchard",
    "market",
    "basket",
    "crate",
    "ladder",
    "branch",
    "blossom",
    "seed",
    "root",
    "leaf",
)
"""Vocabulary of the mail bodies."""

RUN_ARGS = ("--strategy", "select-one", "--action", "delete-discarded", "Archive")
"""Arguments of every run, after the options of its configuration."""

STEPS = ("Step #1", "Step #2", "Step #3", "Step #4", "Step #5")
"""Prefixes of the step headings, in the order a run prints them."""


class Config(NamedTuple):
    """One configuration of the batch."""

    name: str
    """Name of the configuration in the summary."""

    options: tuple[str, ...] = ()
    """Options passed to `mdedup` before {data}`RUN_ARGS`."""

    cache: str = "none"
    """`none` for no cache, `fill` for an empty one, `warm` for a filled one."""

    terminal: bool = False
    """Run in a pseudo-terminal, rather than with the output piped away."""

    preread: bool = False
    """Read every mail into memory before the run."""


CONFIGS = (
    Config("first-skip-j1"),
    Config("first-raw-j1", ("--hash-body", "raw")),
    Config("first-decoded-j1", ("--hash-body", "decoded")),
    Config("first-normalized-j1", ("--hash-body", "normalized")),
    Config("first-skip-j4", ("--jobs", "4")),
    Config("first-decoded-j4", ("--hash-body", "decoded", "--jobs", "4")),
    Config("first-normalized-j4", ("--hash-body", "normalized", "--jobs", "4")),
    Config("first-skip-j8", ("--jobs", "8")),
    Config("fill-skip-j1", cache="fill"),
    Config("warm-skip-j1", cache="warm"),
    Config("warm-content-off-j1", ("--content-threshold", "-1"), cache="warm"),
    Config(
        "warm-thresholds-off-j1",
        ("--content-threshold", "-1", "--size-threshold", "-1"),
        cache="warm",
    ),
    Config("warm-skip-j4", ("--jobs", "4"), cache="warm"),
    Config("warm-skip-j1-terminal", cache="warm", terminal=True),
    Config("warm-skip-j1-preread", cache="warm", preread=True),
)
"""Every configuration the page reports on."""


def run_environment() -> dict[str, str]:
    """The environment of every run, with no variable forcing colors on or off."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"NO_COLOR", "FORCE_COLOR"}
    }
    environment["TERM"] = "xterm-256color"
    environment["COLUMNS"] = "120"
    return environment


def build_corpus(pristine: Path) -> None:
    """Write the pristine maildir, the same on every call thanks to a fixed seed.

    :param pristine: directory to hold the `Archive` maildir.
    """
    if (pristine / "Archive").exists():
        return
    rng = random.Random(42)
    box = pristine / "Archive"
    for folder in ("cur", "new", "tmp"):
        (box / folder).mkdir(parents=True)
    for number in range(MAILS - COPIES):
        fruit = WORDS[number % 16]
        lines = [
            " ".join(rng.choice(WORDS) for _ in range(12)).capitalize() + "."
            for _ in range(48)
        ]
        mail = (
            f"From: {fruit.capitalize()} Orchard <{fruit}@orchard.example>\n"
            "To: market@town.example\n"
            f"Subject: Harvest report {number}\n"
            f"Date: Mon, {1 + number % 28:02d} Sep 2025 "
            f"{number % 24:02d}:{number % 60:02d}:{number % 59:02d} +0000\n"
            f"Message-ID: <harvest-{number}@orchard.example>\n"
            "MIME-Version: 1.0\n"
            'Content-Type: text/plain; charset="utf-8"\n'
            "Content-Transfer-Encoding: 7bit\n"
            "\n" + "\n".join(lines) + "\n"
        ).encode("utf-8")
        (box / "new" / f"{number:06d}.orchard").write_bytes(mail)
        if number % 4 == 0:
            (box / "new" / f"{number:06d}-copy.orchard").write_bytes(mail)


def fresh_copy(pristine: Path, run_dir: Path) -> None:
    """Copy the pristine corpus to `run_dir`, keeping modification times.

    The hash cache checks them, so a warm run finds its entries.

    :param pristine: directory holding the pristine corpus.
    :param run_dir: directory the run reads, emptied first.
    """
    if run_dir.exists():
        shutil.rmtree(run_dir)
    if sys.platform == "darwin":
        # An APFS clone, see the module docstring.
        subprocess.run(
            ("/bin/cp", "-c", "-p", "-R", str(pristine), str(run_dir)), check=True
        )
    else:
        shutil.copytree(pristine, run_dir, copy_function=shutil.copy2)


def drain(descriptor: int) -> None:
    """Read a pseudo-terminal until the run on the other side closes it.

    :param descriptor: the controlling side of the pseudo-terminal.
    """
    while True:
        try:
            if not os.read(descriptor, 65536):
                return
        except OSError:
            return


def run_once(config: Config, workdir: Path, warm_db: Path) -> dict[str, Any]:
    """Run `mdedup` once in `config`, and return what the harness recorded.

    :param config: the configuration to run.
    :param workdir: directory of the batch.
    :param warm_db: hash cache filled by a dry run over the pristine corpus.
    :return: the step times, the durations of hashing and selecting, the number of
        mails read again, and the exit code.
    """
    run_dir = workdir / "run"
    fresh_copy(workdir / "pristine", run_dir)
    options = list(config.options)
    if config.cache != "none":
        if config.cache == "warm":
            shutil.copy2(warm_db, run_dir / "cache.db")
        options += ["--cache-path", "cache.db"]
    if config.preread:
        for path in (run_dir / "Archive" / "new").iterdir():
            path.read_bytes()
    record_path = workdir / "record.json"
    record_path.unlink(missing_ok=True)
    command = (
        sys.executable,
        str(SCRIPT),
        "--harness",
        str(record_path),
        "--",
        *options,
        *RUN_ARGS,
    )
    if config.terminal:
        controller, terminal = pty.openpty()
        process = subprocess.Popen(
            command,
            cwd=run_dir,
            env=run_environment(),
            stdin=subprocess.DEVNULL,
            stdout=terminal,
            stderr=terminal,
        )
        os.close(terminal)
        reader = threading.Thread(target=drain, args=(controller,), daemon=True)
        reader.start()
        code = process.wait(timeout=TIMEOUT)
        reader.join(timeout=10)
        os.close(controller)
    else:
        code = subprocess.run(
            command,
            cwd=run_dir,
            env=run_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT,
            check=False,
        ).returncode
    record: dict[str, Any] = json.loads(record_path.read_text(encoding="UTF-8"))
    marks = [record["marks"][step] for step in STEPS] + [record["marks"]["end"]]
    record["steps"] = [end - start for start, end in pairwise(marks)]
    record["config"] = config.name
    record["exit"] = code
    return record


def run_batch(workdir: Path, samples: int = SAMPLES) -> list[dict[str, Any]]:
    """Build the corpus, fill the warm cache, then run every configuration.

    :param workdir: directory of the batch, created if missing.
    :param samples: runs of each configuration.
    :return: one record per run, also written to `results.jsonl`.
    """
    build_corpus(workdir / "pristine")
    # The warm cache: a dry run over a copy at the path every run reads.
    run_dir = workdir / "run"
    fresh_copy(workdir / "pristine", run_dir)
    subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--harness",
            str(workdir / "record.json"),
            "--",
            "--dry-run",
            "--cache-path",
            "cache.db",
            *RUN_ARGS,
        ),
        cwd=run_dir,
        env=run_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    warm_db = workdir / "warm.db"
    shutil.copy2(run_dir / "cache.db", warm_db)

    records = []
    with (workdir / "results.jsonl").open("w", encoding="UTF-8") as results:
        for sample in range(samples):
            shift = sample % len(CONFIGS)
            for config in CONFIGS[shift:] + CONFIGS[:shift]:
                record = run_once(config, workdir, warm_db)
                record["sample"] = sample
                records.append(record)
                results.write(json.dumps(record) + "\n")
                results.flush()
                print(f"{sample} {config.name} exit={record['exit']}", flush=True)
    return records


def summarize(records: list[dict[str, Any]], workdir: Path) -> None:
    """Print the median of each step per configuration, then the figures of the page.

    :param records: the records of {func}`run_batch`.
    :param workdir: directory of the batch, holding the warm cache.
    """
    runs: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        runs.setdefault(record["config"], []).append(record)

    def step(name: str, index: int) -> float:
        return float(statistics.median(run["steps"][index] for run in runs[name]))

    def total(name: str) -> float:
        """Median of steps 1 to 4: the report of step 5 is left out."""
        return float(statistics.median(sum(run["steps"][:4]) for run in runs[name]))

    print(
        f"\n{'configuration':24} {'load':>5} {'hash':>5} {'select':>6} "
        f"{'act':>5} {'total':>6} {'re-read':>8} exit"
    )
    for name, group in runs.items():
        codes = sorted({run["exit"] for run in group})
        reread = sorted({run["rereads"] for run in group})
        print(
            f"{name:24} {step(name, 0):5.2f} {step(name, 1):5.2f} "
            f"{step(name, 2):6.2f} {step(name, 3):5.2f} {total(name):6.2f} "
            f"{reread!s:>8} {codes}"
        )

    print("\nShares of each step:")
    for name in ("first-skip-j1", "warm-skip-j1"):
        steps = [step(name, index) for index in range(4)]
        share_text = ", ".join(f"{value / sum(steps):.0%}" for value in steps)
        print(f"  {name}: {share_text} of {sum(steps):.1f}s")

    first, warm = "first-skip-j1", "warm-skip-j1"
    print("\nCache:")
    print(f"  hashing {step(first, 1) / step(warm, 1):.1f}x faster")
    print(f"  whole run {total(first) / total(warm):.1f}x faster")
    print(f"  filling costs {total('fill-skip-j1') / total(first) - 1:+.0%}")
    size = (workdir / "warm.db").stat().st_size
    print(f"  {size / MAILS:.0f} bytes per mail")
    print(
        f"  step 3 of a cached run: {step(warm, 2):.2f}s, "
        f"{step('warm-skip-j1-preread', 2):.2f}s with the mails in memory"
    )

    print("\nParallel hashing speedups:")
    for mode in ("skip", "decoded", "normalized"):
        speedup = step(f"first-{mode}-j1", 1) / step(f"first-{mode}-j4", 1)
        print(f"  {mode}, 4 jobs: {speedup:.1f}x")
    print(f"  skip, 8 jobs: {step(first, 1) / step('first-skip-j8', 1):.1f}x")
    print(f"  cached run, 4 jobs: {total(warm) / total('warm-skip-j4'):.1f}x")

    print("\nBody hashing, relative to skip (hashing step, whole first run):")
    for mode in ("raw", "decoded", "normalized"):
        name = f"first-{mode}-j1"
        print(
            f"  {mode}: {step(name, 1) / step(first, 1):.2f}x, "
            f"{total(name) / total(first):.2f}x"
        )

    terminal = {run["sample"]: run for run in runs["warm-skip-j1-terminal"]}
    output_shares: list[float] = [
        1 - sum(run["steps"]) / sum(terminal[run["sample"]]["steps"])
        for run in runs[warm]
    ]
    print(
        f"\nOutput in a terminal: {statistics.median(output_shares):+.1%} of the run, "
        f"from {min(output_shares):+.1%} to {max(output_shares):+.1%} across passes"
    )


def harness(record_path: Path, args: list[str]) -> None:
    """Run `mdedup` in this process, recording its step times and its re-reads.

    :param record_path: file the record is written to when the run ends.
    :param args: the arguments of `mdedup`.
    """
    marks: dict[str, float] = {}
    durations: dict[str, float] = {}
    rereads = [0]

    echo_step = cli.echo_step

    def timed_echo_step(title: str) -> None:
        marks[title.partition(" - ")[0]] = time.perf_counter()
        echo_step(title)

    hash_all = Deduplicate.hash_all
    build_sets = Deduplicate.build_sets

    def timed_hash_all(self: Deduplicate) -> None:
        start = time.perf_counter()
        hash_all(self)
        durations["hash_all"] = time.perf_counter() - start

    def timed_build_sets(self: Deduplicate) -> None:
        start = time.perf_counter()
        build_sets(self)
        durations["build_sets"] = time.perf_counter() - start

    hydrate = DedupMailMixin.hydrate

    def counted_hydrate(self: DedupMailMixin) -> None:
        if not self.is_hydrated:
            rereads[0] += 1
        hydrate(self)

    cli.echo_step = timed_echo_step
    Deduplicate.hash_all = timed_hash_all  # type: ignore[method-assign]
    Deduplicate.build_sets = timed_build_sets  # type: ignore[method-assign]
    DedupMailMixin.hydrate = counted_hydrate  # type: ignore[method-assign]

    def dump() -> None:
        marks["end"] = time.perf_counter()
        record = {"marks": marks, "durations": durations, "rereads": rereads[0]}
        record_path.write_text(json.dumps(record), encoding="UTF-8")

    atexit.register(dump)
    cli.mdedup(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workdir",
        type=Path,
        default=WORKDIR,
        help="Directory of the corpus and the results.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=SAMPLES,
        help="Runs of each configuration.",
    )
    parser.add_argument(
        "--harness",
        type=Path,
        metavar="RECORD",
        help="Run mdedup once with the arguments after --, and write its record.",
    )
    parser.add_argument("mdedup_args", nargs="*", help=argparse.SUPPRESS)
    options = parser.parse_args()

    if options.harness:
        harness(options.harness, options.mdedup_args)
    else:
        options.workdir.mkdir(parents=True, exist_ok=True)
        summarize(run_batch(options.workdir, options.samples), options.workdir)
