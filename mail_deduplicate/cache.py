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
"""Persistent cache of mail hashes, so a second run does not re-parse unchanged mails.

Hashing dominates a run, and it is pure work: the same mail, hashed with the same
settings, always produces the same result. Storing that result lets a later run skip
opening and parsing every mail it has already seen. See:
https://github.com/kdeldycke/mail-deduplicate/issues/87

Correctness rests on two independent guards:

- A fingerprint of every setting feeding the hash. Anything else invalidates the whole
  database, as no entry produced under different settings can be trusted.
- A per-mail staleness key of `(size, mtime)`, taken from the file backing the mail
  *before* it is read, so a mail modified mid-run is re-hashed by the next one instead
  of being trusted.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from pathlib import Path
from typing import NamedTuple

from platformdirs import user_cache_path

from .mail_box import resolve_mail_path

TYPE_CHECKING = False
if TYPE_CHECKING:
    from mailbox import Mailbox

    from .cli import Config


SCHEMA_VERSION = "1"
"""Bumped whenever the table layout changes, to discard databases of older shapes."""

CACHED_SETTINGS = ("hash_headers", "hash_body", "time_source")
"""Configuration keys whose value changes what gets cached.

`hash_headers` and `hash_body` change the hash itself. `time_source` changes the
timestamp memoized alongside it. The minimal-headers floor is derived from the number
of hash headers, so it is covered by the first one.
"""


class StaleKey(NamedTuple):
    """Identifies the version of the file backing a mail."""

    size: int
    mtime_ns: int


class CacheEntry(NamedTuple):
    """What is worth keeping about a hashed mail.

    The hash is the point. The two scalars are what `dehydrate()` memoizes to spare
    the later steps a re-read, so restoring them is what actually lets a cached mail
    stay unparsed. `mail_size` is only known when the body was hashed, and
    `timestamp` is `None` for a mail whose `Date` header could not be parsed.
    """

    mail_hash: str
    timestamp: float | None
    mail_size: int | None


def default_cache_dir() -> Path:
    """Location of the cache database, following each platform's conventions.

    `~/Library/Caches/mdedup` on macOS, `$XDG_CACHE_HOME/mdedup` on other POSIX
    systems, and `%LOCALAPPDATA%\\mdedup\\Cache` on Windows.

    `appauthor` is turned off because there is no vendor to namespace under: leaving
    it unset would have Windows fall back to the application name and nest the cache
    one level deeper, under `mdedup\\mdedup\\Cache`.
    """
    return user_cache_path("mdedup", appauthor=False)


def default_cache_path() -> Path:
    """Full path of the cache database."""
    return default_cache_dir().joinpath("hashes.db")


def settings_fingerprint(conf: Config) -> str:
    """Digest of every setting that changes what a cached entry would hold."""
    material = "\n".join(
        f"{key}={conf[key]!r}"  # type: ignore[literal-required]
        for key in CACHED_SETTINGS
    )
    return hashlib.sha256(f"{SCHEMA_VERSION}\n{material}".encode()).hexdigest()


def open_cache(conf: Config) -> HashCache | None:
    """Opens the hash cache the configuration asks for, if it asks for one at all.

    A cache only ever saves work, so a database that cannot be opened, on a
    read-only or full filesystem for instance, is reported and skipped instead of
    taking the whole run down with it.
    """
    if not conf["cache"]:
        return None

    path = Path(conf["cache_path"] or default_cache_path())
    try:
        cache = HashCache(path, settings_fingerprint(conf))
    except (OSError, sqlite3.Error) as expt:
        logging.warning(f"Cannot open the hash cache at {path}: {expt}")
        logging.warning("Carry on without it, hashing every mail.")
        return None

    logging.info(f"Use hash cache at {path}.")
    return cache


class HashCache:
    """A mail hash cache backed by SQLite, keyed by mail identity.

    Opened for the whole run and committed once at the end, so an interrupted run
    leaves the database as it found it.
    """

    WRITE_BATCH: int = 512
    """Rows buffered before being handed to SQLite in one `executemany()`.

    Inserting one row at a time costs more in statement overhead than in storage.
    """

    def __init__(self, path: Path, fingerprint: str) -> None:
        self.path = path
        self.hits = 0
        self.misses = 0

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id   INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS hashes (
                source_id INTEGER NOT NULL REFERENCES sources(id),
                mail_id   TEXT    NOT NULL,
                size      INTEGER NOT NULL,
                mtime_ns  INTEGER NOT NULL,
                mail_hash TEXT    NOT NULL,
                timestamp REAL,
                mail_size INTEGER,
                PRIMARY KEY (source_id, mail_id)
            ) WITHOUT ROWID;
            """,
        )
        self._enforce_fingerprint(fingerprint)

        # Only ever holds the mails read but not yet hashed, which the caller bounds
        # to one batch, so it does not grow with the size of the corpus.
        self._pending: dict[tuple[str, str], StaleKey] = {}

        self._source_ids: dict[str, int] = {}
        """Box paths interned as integers, so a row's key does not repeat the whole
        path of its box. Bounded by the number of boxes."""

        self._writes: list[tuple] = []
        """Rows waiting to be flushed."""

    def _source_id(self, source_path: str) -> int:
        """Interns a box path, inserting it on first sight."""
        source_id = self._source_ids.get(source_path)
        if source_id is None:
            row = self.connection.execute(
                "SELECT id FROM sources WHERE path = ?",
                (source_path,),
            ).fetchone()
            if row:
                source_id = row[0]
            else:
                cursor = self.connection.execute(
                    "INSERT INTO sources (path) VALUES (?)",
                    (source_path,),
                )
                source_id = cursor.lastrowid
            assert source_id is not None
            self._source_ids[source_path] = source_id
        return source_id

    def _enforce_fingerprint(self, fingerprint: str) -> None:
        """Drop every entry when the settings feeding the hashes have changed."""
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = 'fingerprint'",
        ).fetchone()
        if row and row[0] == fingerprint:
            return
        if row:
            logging.info("Hashing settings changed: discard the whole hash cache.")
        self.connection.execute("DELETE FROM hashes")
        self.connection.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('fingerprint', ?)",
            (fingerprint,),
        )
        self.connection.commit()

    def _stale_key(self, box: Mailbox, mail_id: str) -> StaleKey | None:
        """Size and modification time of the file backing a mail.

        Folder-based boxes give each mail its own file, so the key tracks that mail
        alone. File-based ones pack every mail into the box's single file, so all of
        them share its key and any edit to the box invalidates the lot: their mail
        IDs are byte offsets that shift as soon as a mail is added or removed.
        """
        try:
            stat = os.stat(resolve_mail_path(box, mail_id))
        except (OSError, KeyError) as expt:
            # An unreachable mail is simply never cached: the caller still gets its
            # chance to read it, and to fail on its own terms if it too cannot.
            logging.debug(f"Cannot stat mail {mail_id} of {box._path}: {expt}")
            return None
        return StaleKey(stat.st_size, stat.st_mtime_ns)

    def lookup(self, box: Mailbox, mail_id: str) -> CacheEntry | None:
        """Returns the entry cached for a mail, if it is still valid.

        The staleness key is taken here, before the caller reads the mail, so a mail
        modified between this check and its hashing is caught by the next run rather
        than trusted.
        """
        stale_key = self._stale_key(box, mail_id)
        if stale_key is None:
            return None

        self._pending[(box._path, mail_id)] = stale_key
        row = self.connection.execute(
            "SELECT mail_hash, timestamp, mail_size FROM hashes "
            "WHERE source_id = ? AND mail_id = ? AND size = ? AND mtime_ns = ?",
            (self._source_id(box._path), mail_id, stale_key.size, stale_key.mtime_ns),
        ).fetchone()

        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        # Nothing left to record for a mail the caller will not read.
        del self._pending[(box._path, mail_id)]
        return CacheEntry(*row)

    def store(self, source_path: str, mail_id: str, entry: CacheEntry) -> None:
        """Record the hash of a freshly read mail, under the key taken by `lookup()`.

        Silently skipped for a mail that was never looked up, as there is then no
        staleness key that provably predates the read.
        """
        stale_key = self._pending.pop((source_path, mail_id), None)
        if stale_key is None:
            return
        self._writes.append((
            self._source_id(source_path),
            mail_id,
            stale_key.size,
            stale_key.mtime_ns,
            entry.mail_hash,
            entry.timestamp,
            entry.mail_size,
        ))
        if len(self._writes) >= self.WRITE_BATCH:
            self._flush()

    def _flush(self) -> None:
        """Hand the buffered rows to SQLite, still inside the run's transaction."""
        if not self._writes:
            return
        self.connection.executemany(
            "INSERT OR REPLACE INTO hashes "
            "(source_id, mail_id, size, mtime_ns, mail_hash, timestamp, mail_size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            self._writes,
        )
        self._writes.clear()

    def forget(self, source_path: str, mail_id: str) -> None:
        """Drop the staleness key of a mail that will not be recorded."""
        self._pending.pop((source_path, mail_id), None)

    def commit(self) -> None:
        """Flush everything recorded during the run, in one transaction."""
        self._flush()
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
