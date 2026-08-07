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

import re
import shutil
import sqlite3
from mailbox import Maildir, mbox
from pathlib import Path
from unittest import mock

import pytest

from mail_deduplicate.cache import HashCache, default_cache_dir, default_cache_path
from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import BoxFormat

from .conftest import MailFactory

DEDUP_ARGS = ("--strategy=select-newest", "--action=delete-discarded", "--dry-run")
"""A run that exercises every step without touching the mails on disk."""


@pytest.fixture()
def count_hashes(monkeypatch):
    """Counts the mails actually hashed, which a cache hit must not be.

    Restoring a mail from the cache skips its parsing entirely, so `hash_key()` is
    the sharpest signal that the file was read rather than served from the database.
    """
    hashed: list[str] = []
    original = DedupMailMixin.hash_key

    def spy(self) -> str:
        hashed.append(str(self.mail_id))
        return original(self)

    monkeypatch.setattr(DedupMailMixin, "hash_key", spy)
    return hashed


def metrics(output: str) -> dict[str, str]:
    """Extracts the name and value of every metric of a run's report tables."""
    parsed = {}
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split("│") if cell.strip()]
        if len(cells) >= 2 and re.fullmatch(r"\d+", cells[1]):
            parsed[cells[0]] = cells[1]
    return parsed


def mail_files(box_path: str) -> list[Path]:
    """Every mail file of a folder-based box, in a stable order."""
    return sorted(p for p in Path(box_path).rglob("*") if p.is_file())


def test_cache_is_off_by_default(invoke, make_box, tmp_path, monkeypatch):
    """No database is created unless the user opts in."""
    default_db = tmp_path.joinpath("hashes.db")
    monkeypatch.setattr(
        "mail_deduplicate.cache.default_cache_path",
        lambda: default_db,
    )
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    assert not default_db.exists()
    # The same run with the flag does produce it, so the check above is not vacuous.
    assert invoke("--cache", *DEDUP_ARGS, box_path).exit_code == 0
    assert default_db.is_file()


def test_default_cache_path_sits_under_the_cache_dir():
    """The database lands in the platform's cache location, not next to the mails."""
    assert default_cache_path().parent == default_cache_dir()
    assert default_cache_path().name.endswith(".db")


@pytest.mark.parametrize("box_format", tuple(BoxFormat), ids=str)
@pytest.mark.parametrize("jobs", (1, 2))
def test_warm_run_matches_uncached_run(
    invoke, make_box, tmp_path, box_format, jobs, count_hashes
):
    """A run served from the cache must decide exactly what an uncached run does.

    The report accounts for every mail through the four steps, so a stale hash would
    surface as a different grouping and different metrics. Swept over every format,
    as each one locates its mails differently, and over the sequential and parallel
    hashing paths, as only the former reads the cache one mail at a time.

    MH, Babyl and MMDF are never autodetected, so the format is forced.
    """
    mails = [
        MailFactory(message_id="<a@nohost.com>"),
        MailFactory(message_id="<a@nohost.com>"),
        MailFactory(message_id="<b@nohost.com>"),
    ]
    box_path, _, _ = make_box(box_format.base_class, mails)
    cache_db = tmp_path.joinpath("hashes.db")
    args = (f"--input-format={box_format}", f"--jobs={jobs}", *DEDUP_ARGS)

    uncached = invoke(*args, box_path)
    cold = invoke(f"--cache-path={cache_db}", *args, box_path)
    count_hashes.clear()
    warm = invoke(f"--cache-path={cache_db}", *args, box_path)

    assert uncached.exit_code == cold.exit_code == warm.exit_code == 0
    # The warm run was really served by the cache, so the comparison below is about
    # restored hashes rather than freshly computed ones.
    assert count_hashes == []
    assert metrics(uncached.stdout) == metrics(cold.stdout)
    assert metrics(uncached.stdout) == metrics(warm.stdout)
    # The metrics really were parsed, rather than two empty dicts comparing equal.
    assert metrics(uncached.stdout)["Found"] == "3"


def test_warm_run_skips_hashing(invoke, make_box, tmp_path, count_hashes):
    """The point of the cache: a second run does not re-hash what it already knows."""
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert len(count_hashes) == 2

    count_hashes.clear()
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert count_hashes == []


def test_cache_flag_uses_the_default_location(invoke, make_box, tmp_path, monkeypatch):
    """`--cache` alone puts the database in the platform cache directory."""
    monkeypatch.setattr(
        "mail_deduplicate.cache.default_cache_path",
        lambda: tmp_path.joinpath("hashes.db"),
    )
    box_path, _, _ = make_box(Maildir, [MailFactory()])

    assert invoke("--cache", *DEDUP_ARGS, box_path).exit_code == 0

    assert tmp_path.joinpath("hashes.db").is_file()


@pytest.mark.parametrize(
    "changed_option",
    (
        "--hash-header=message-id",
        "--hash-body=raw",
        "--time-source=ctime",
    ),
)
def test_settings_change_discards_the_cache(
    invoke, make_box, tmp_path, count_hashes, changed_option
):
    """Every option feeding a cached value invalidates the whole database.

    An entry produced under different hashing settings cannot be told apart from a
    valid one by its staleness key alone, so none of them may survive.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert len(count_hashes) == 2

    count_hashes.clear()
    result = invoke(f"--cache-path={cache_db}", changed_option, *DEDUP_ARGS, box_path)

    assert result.exit_code == 0
    # Every mail is hashed again, none was served from the stale database.
    assert len(count_hashes) == 2


def test_modified_mail_is_rehashed(invoke, make_box, tmp_path, count_hashes):
    """A mail whose file changed must not be served from the cache.

    Maildir keys survive a rewrite, so only the staleness key stands between a
    modified mail and a hash computed from its previous content.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert len(count_hashes) == 2

    # Rewrite one mail in place, under the very same file name.
    target = mail_files(box_path)[0]
    target.write_bytes(
        MailFactory(message_id="<rewritten@nohost.com>", body="Rewritten.\n").render(),
    )

    count_hashes.clear()
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0

    # Only the rewritten mail is read again; its untouched sibling stays cached.
    assert len(count_hashes) == 1


def test_edited_file_based_box_invalidates_every_mail(
    invoke, make_box, tmp_path, count_hashes
):
    """Mails of an mbox share the box's file and are keyed by byte offsets, which
    shift as soon as a mail is added or removed. Editing the box must therefore
    invalidate all of its mails at once, not just the ones that moved."""
    box_path, _, _ = make_box(mbox, [MailFactory(), MailFactory()])
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert len(count_hashes) == 2

    box = mbox(box_path, create=False)
    box.lock()
    box.add(MailFactory(message_id="<appended@nohost.com>").render())
    box.close()

    count_hashes.clear()
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0

    assert len(count_hashes) == 3


@pytest.mark.parametrize("cache_args", ((), ("--cache-path",)))
def test_mail_vanishing_mid_run_is_skipped(
    invoke, make_box, tmp_path, monkeypatch, cache_args
):
    """A mail removed between the box listing it and the run reading it is skipped.

    Regression test: the hashing step used to walk the box with `iteritems()`, which
    swallows that race. Walking the keys instead, so a cached mail is never read,
    has to keep swallowing it rather than dying on a `KeyError`.
    """
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])
    args = [f"{arg}={tmp_path / 'hashes.db'}" for arg in cache_args]

    doomed = mail_files(box_path)[0]
    original_keys = Maildir.iterkeys

    def drop_one(self):
        """List every mail, then delete one before the caller gets to read it."""
        keys = list(original_keys(self))
        doomed.unlink(missing_ok=True)
        return iter(keys)

    monkeypatch.setattr(Maildir, "iterkeys", drop_one)
    result = invoke(*args, *DEDUP_ARGS, box_path)

    # The mail is skipped instead of blowing up on the key it no longer answers to.
    assert "KeyError" not in result.stderr
    assert metrics(result.stdout)["Retained"] == "1"
    # It does leave the run one mail short of the count taken when the box was
    # opened, which the statistics self-check reports as it would for any gap.
    assert result.exit_code == 115
    assert "Metrics appear inconsistent" in result.stderr


def test_unusable_cache_does_not_abort_the_run(invoke, make_box, tmp_path):
    """A database that cannot be opened is reported and skipped.

    The cache only ever saves work, so an unwritable location, a read-only home or a
    full disk must not take the deduplication down with it.
    """
    # A regular file where the database's parent directory should be, so creating it
    # fails the same way an unwritable location would.
    blocker = tmp_path.joinpath("blocker")
    blocker.write_text("not a directory")
    box_path, _, _ = make_box(Maildir, [MailFactory(), MailFactory()])

    result = invoke(f"--cache-path={blocker / 'hashes.db'}", *DEDUP_ARGS, box_path)

    assert result.exit_code == 0
    assert "Cannot open the hash cache" in result.stderr
    assert "Carry on without it" in result.stderr
    # The run still went through every step and accounted for both mails.
    assert metrics(result.stdout)["Retained"] == "2"


def test_rejected_mails_are_not_cached(invoke, make_box, tmp_path):
    """A rejection depends on more than the hash, so it is recomputed every run."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    cache_db = tmp_path.joinpath("hashes.db")
    too_few = (
        "--hash-header=x-absent-one",
        "--hash-header=x-absent-two",
        "--hash-header=x-absent-three",
        "--hash-header=subject",
    )

    result = invoke(f"--cache-path={cache_db}", *too_few, "--hash-only", box_path)

    assert result.exit_code == 0
    assert "Rejecting" in result.stderr
    with sqlite3.connect(cache_db) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]
    assert rows == 0


def cached_rows(cache_db) -> int:
    """Number of mail entries held by a cache database."""
    with sqlite3.connect(cache_db) as connection:
        count = connection.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]
    return int(count)


def test_deleted_mails_are_pruned(invoke, make_box, tmp_path):
    """Mails removed from a box must not keep their entry forever.

    A cache nobody prunes only grows, holding hashes for mails that no longer exist.
    """
    mails = [MailFactory(message_id=f"<d{i}@nohost.com>") for i in range(5)]
    box_path, _, _ = make_box(Maildir, mails)
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    assert cached_rows(cache_db) == 5

    for doomed in mail_files(box_path)[:3]:
        doomed.unlink()

    result = invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path)

    assert result.exit_code == 0
    assert cached_rows(cache_db) == 2
    assert "3 stale entries dropped" in result.stderr


def test_vanished_box_is_pruned(invoke, make_box, tmp_path):
    """A box that was deleted or moved takes all of its entries with it."""
    kept_path, _, _ = make_box(Maildir, [MailFactory(message_id="<k@nohost.com>")])
    gone_path, _, _ = make_box(
        Maildir, [MailFactory(message_id=f"<g{i}@nohost.com>") for i in range(4)]
    )
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, kept_path).exit_code == 0
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, gone_path).exit_code == 0
    assert cached_rows(cache_db) == 5

    shutil.rmtree(gone_path)

    # A run over the surviving box alone is enough to notice the other one is gone.
    result = invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, kept_path)

    assert result.exit_code == 0
    assert cached_rows(cache_db) == 1
    assert "4 stale entries dropped" in result.stderr


def test_unvisited_boxes_are_left_alone(invoke, make_box, tmp_path):
    """Only the boxes a run opens are pruned mail by mail.

    Every mail of a box nobody opened is absent from the run's sightings for the
    plain reason that nobody looked, which is no evidence that it is gone. Pruning
    on that basis would empty the cache of every box not passed on the command line.
    """
    first_path, _, _ = make_box(Maildir, [MailFactory(message_id="<x@nohost.com>")])
    second_path, _, _ = make_box(
        Maildir, [MailFactory(message_id=f"<y{i}@nohost.com>") for i in range(3)]
    )
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, first_path).exit_code == 0
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, second_path).exit_code == 0
    assert cached_rows(cache_db) == 4

    # Re-run over the first box only: the second one still exists, untouched.
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, first_path).exit_code == 0

    assert cached_rows(cache_db) == 4


def test_run_survives_a_database_held_by_another_run(invoke, make_box, tmp_path):
    """A database another run is writing must not take this one down.

    Runs sharing a cache contend on the write burst each performs at the end. By
    then the deduplication is done, so losing that race may only cost the next run
    its head start. Simulated by holding the write lock for longer than the loser is
    willing to wait.
    """
    box_path, _, _ = make_box(
        Maildir, [MailFactory(message_id=f"<h{i}@nohost.com>") for i in range(3)]
    )
    cache_db = tmp_path.joinpath("hashes.db")

    # Seed the database, then grab and hold its write lock.
    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0
    holder = sqlite3.connect(cache_db, timeout=0, isolation_level="EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        # Waiting the full lock timeout would stall the suite, so cut it short.
        with mock.patch.object(HashCache, "LOCK_TIMEOUT", 0.1):
            result = invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path)
    finally:
        holder.rollback()
        holder.close()

    # The deduplication still reported its results, only the cache write was lost.
    assert result.exit_code == 0
    assert metrics(result.stdout)["Retained"] == "3"
    assert "Cannot" in result.stderr and "hash cache" in result.stderr


def test_cache_survives_a_corpus_growing_between_runs(invoke, make_box, tmp_path):
    """Mails added to a folder-based box after a run join the cached ones."""
    box_path, _, _ = make_box(Maildir, [MailFactory(message_id="<a@nohost.com>")])
    cache_db = tmp_path.joinpath("hashes.db")

    assert invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path).exit_code == 0

    box = Maildir(box_path, create=False)
    box.lock()
    box.add(MailFactory(message_id="<b@nohost.com>").render())
    box.close()

    result = invoke(f"--cache-path={cache_db}", *DEDUP_ARGS, box_path)

    assert result.exit_code == 0
    assert metrics(result.stdout)["Found"] == "2"
    assert metrics(result.stdout)["Retained"] == "2"
