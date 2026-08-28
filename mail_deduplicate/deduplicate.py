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
"""The deduplication pipeline: group mails by hash, settle each duplicate set, keep
score.

The `Deduplicate` orchestrator drives the whole run. Both of its expensive steps,
hashing and selection, can fan out across worker processes: the module-level
`_`-prefixed functions are the halves that run inside a worker.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from difflib import unified_diff
from enum import Enum, unique
from functools import cached_property
from itertools import combinations, islice
from pathlib import Path
from typing import NamedTuple, cast

from click_extra import (
    context,
    get_current_context,
    get_current_theme,
    progressbar,
)

from . import StrEnum
from .cache import CacheEntry, HashCache, open_cache
from .mail import TimeSource, TooFewHeaders
from .mail_box import (
    FOLDER_FORMAT_CLASSES,
    iter_mail_ids,
    open_box,
    resolve_mail_path,
)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from mailbox import Mailbox

    from .cli import Config
    from .mail import DedupMailMixin


@unique
class Stat(Enum):
    """All tracked statistics.

    The member's name carries the category as its `MAIL_`/`SET_` prefix, and its
    value the description shown in the final report.
    """

    MAIL_FOUND = "Total number of mails encountered from all mail sources."
    MAIL_REJECTED = (
        "Number of mails rejected individually because they were unparsable or "
        "did not have enough metadata to compute hashes."
    )
    MAIL_RETAINED = "Number of valid mails parsed and retained for deduplication."
    MAIL_HASHES = "Number of unique hashes."
    MAIL_UNIQUE = (
        "Number of unique mails (which were automatically added to selection)."
    )
    MAIL_DUPLICATES = (
        "Number of duplicate mails (sum of mails in all duplicate sets with at "
        "least 2 mails)."
    )
    MAIL_SKIPPED = (
        "Number of mails ignored in the selection step because the whole set "
        "they belong to was skipped."
    )
    MAIL_DISCARDED = "Number of mails discarded from the final selection."
    MAIL_SELECTED = (
        "Number of mails kept in the final selection on which the "
        "action will be performed."
    )
    MAIL_COPIED = "Number of mails copied from their original mailbox to another."
    MAIL_MOVED = "Number of mails moved from their original mailbox to another."
    MAIL_DELETED = "Number of mails deleted from their mailbox in-place."
    MAIL_HARDLINKED = (
        "Number of mails replaced in-place by a hardlink to the copy kept in their "
        "duplicate set."
    )
    MAIL_HARDLINK_SKIPPED = (
        "Number of mails left untouched by the hardlinking action, because they "
        "could not be linked to their copy or already were."
    )
    SET_TOTAL = "Total number of duplicate sets."
    SET_SINGLE = (
        "Total number of sets containing only a single mail with no applicable "
        "strategy. They were automatically kept in the final selection."
    )
    SET_SKIPPED_ENCODING = (
        "Number of sets skipped from the selection process because they had "
        "encoding issues."
    )
    SET_SKIPPED_SIZE = (
        "Number of sets skipped from the selection process because they were "
        "too dissimilar in size."
    )
    SET_SKIPPED_CONTENT = (
        "Number of sets skipped from the selection process because they were "
        "too dissimilar in content."
    )
    SET_SKIPPED_TIMESTAMP = (
        "Number of sets skipped from the selection process because a timestamp "
        "could not be derived for some of their mails."
    )
    SET_SKIPPED_STRATEGY = (
        "Number of sets skipped from the selection process because the strategy "
        "could not be applied."
    )
    SET_DEDUPLICATED = (
        "Number of valid sets on which the selection strategy was successfully applied."
    )

    @property
    def description(self) -> str:
        """The description of the statistic, shown in the final report."""
        return self.value

    @property
    def category(self) -> str:
        """Whether the statistic counts mails or sets, read off the member's name."""
        return self.name.partition("_")[0].lower()


class SizeDiffAboveThreshold(Exception):
    """Difference in mail size is greater than [threshold](https://kdeldycke.github.io/mail-deduplicate/cli.html)."""


class ContentDiffAboveThreshold(Exception):
    """Difference in mail content is greater than [threshold](https://kdeldycke.github.io/mail-deduplicate/cli.html)."""


class MissingTimestamps(Exception):
    """Some mails of a duplicate set have no timestamp, so they cannot be compared by
    time-based strategies.

    Happens for mails without a parseable `Date` header, when the timestamp is
    sourced from it.
    """


class BodyHasher(StrEnum):
    """Enumeration of available body hashing methods."""

    SKIP = "skip"
    RAW = "raw"
    NORMALIZED = "normalized"

    @property
    def function(self) -> Callable[[DedupMailMixin], str]:
        """The callable producing this member's body hash for one mail."""
        return {
            BodyHasher.SKIP: lambda _: "",
            BodyHasher.RAW: lambda mail: mail.hash_raw_body,
            BodyHasher.NORMALIZED: lambda mail: mail.hash_normalized_body,
        }[self]


class DuplicateSet:
    """A set of mails sharing the same hash.

    Implements all the safety checks required before we can apply any selection
    strategy.
    """

    def __init__(
        self, hash_key: str, mail_set: Iterable[DedupMailMixin], conf: Config
    ) -> None:
        """Load-up the duplicate set of mail and freeze pool.

        Once loaded-up, the pool of parsed mails is considered frozen for the rest of
        the duplicate set's life. This allows aggressive caching of lazy instance
        attributes depending on the pool content.
        """
        self.hash_key: str = hash_key

        self.selection: set[DedupMailMixin] = set()
        """Mails selected after application of selection strategy."""

        self.unique: set[DedupMailMixin] = set()
        """The subset of the selection no strategy ever ruled on.

        A mail alone in its set has no copy to be compared to, so it is kept
        without any criterion picking it over another. Held apart from the rest
        of the selection so a destructive action can leave it alone. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/1053
        """

        self.discard: set[DedupMailMixin] = set()
        """Mails discarded after application of selection strategy."""

        self.conf = conf
        """Configuration shared from the main deduplication process."""

        self.pool: frozenset[DedupMailMixin] = frozenset(mail_set)
        """Pool referencing all duplicated mails and their attributes."""

        self.stats: Counter[Stat] = Counter()
        """Set metrics. Unset statistics naturally read as zero."""

        self.stats[Stat.MAIL_DUPLICATES] += self.size

        logging.debug(f"{self!r} created.")

    def __repr__(self) -> str:
        """Print internal raw states for debugging."""
        return f"<{self.__class__.__name__} hash={self.hash_key} size={self.size}>"

    @cached_property
    def size(self) -> int:
        """Returns the number of mails in the duplicate set."""
        return len(self.pool)

    @cached_property
    def timestamps(self) -> tuple[float, ...]:
        """Returns the timestamps of all mails in the set.

        Raises `MissingTimestamps` if a timestamp could not be derived for some
        mails, naming them so users can locate and fix them. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/132
        """
        timestamps = []
        undated = []
        for mail in self.pool:
            if mail.timestamp is None:
                undated.append(mail)
            else:
                timestamps.append(mail.timestamp)
        if undated:
            raise MissingTimestamps(
                "No timestamp for "
                + ", ".join(sorted(repr(mail) for mail in undated))
                + "."
            )
        return tuple(timestamps)

    @cached_property
    def newest_timestamp(self) -> float:
        """Returns the newest timestamp among all mails in the set."""
        return max(self.timestamps)

    @cached_property
    def oldest_timestamp(self) -> float:
        """Returns the oldest timestamp among all mails in the set."""
        return min(self.timestamps)

    @cached_property
    def biggest_size(self) -> int:
        """Returns the biggest size among all mails in the set."""
        return max(mail.size for mail in self.pool)

    @cached_property
    def smallest_size(self) -> int:
        """Returns the smallest size among all mails in the set."""
        return min(mail.size for mail in self.pool)

    def check_differences(self) -> set[DedupMailMixin]:
        """Checks all mails of the set against each other, for size and content
        differences within the limits imposed by the thresholds.

        Instead of rejecting the whole set on the first offending pair, the mails
        involved in the most offending pairs are greedily set aside until every
        remaining pair passes the thresholds. This keeps a single outlier from
        preventing the deduplication of the true copies sharing its set. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/851

        Returns the mails to set aside, empty if the whole pool already passes.

        Raises `SizeDiffAboveThreshold` or `ContentDiffAboveThreshold` if fewer
        than 2 mails would remain, in which case there is no coherent core of
        duplicates and the whole set is to be skipped, as before.
        """
        size_threshold = self.conf["size_threshold"]
        content_threshold = self.conf["content_threshold"]

        logging.debug("Check mail differences are below the thresholds.")
        if size_threshold < 0 and content_threshold < 0:
            return set()

        # Every pair is within the size threshold as soon as the extremes are, and
        # mails sharing a body cannot differ in content. Deciding both of those over
        # the whole set is linear, where confirming them pair by pair is not, and a
        # set of true copies satisfies them: the usual case never walks the pairs.
        spread_ok = size_threshold < 0 or (
            self.biggest_size - self.smallest_size <= size_threshold
        )
        bodies = {mail.hash_raw_body for mail in self.pool}
        if spread_ok and (content_threshold < 0 or len(bodies) == 1):
            return set()

        # Adjacency of mails linked by a pair exceeding a threshold.
        offending_peers: dict[DedupMailMixin, set[DedupMailMixin]] = {}
        size_offense = False
        # How far two mails differ in content is a property of their two bodies, not
        # of the mails carrying them, so each distinct pair of bodies is diffed once
        # however many mails share them. Diffing is the expensive part of this walk.
        diffs: dict[frozenset[str], int] = {}
        for mail_a, mail_b in combinations(self.pool, 2):
            offense = False
            if size_threshold >= 0:
                size_difference = abs(mail_a.size - mail_b.size)
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {size_difference} bytes "
                    "in size.",
                )
                if size_difference > size_threshold:
                    offense = size_offense = True

            if not offense and content_threshold >= 0:
                pair = frozenset((mail_a.hash_raw_body, mail_b.hash_raw_body))
                if pair not in diffs:
                    # A single body means both mails carry it: nothing to diff.
                    diffs[pair] = 0 if len(pair) == 1 else self.diff(mail_a, mail_b)
                content_difference = diffs[pair]
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {content_difference} bytes "
                    "in content.",
                )
                if content_difference > content_threshold:
                    offense = True
                    if self.conf["show_diff"]:
                        logging.info(self.pretty_diff(mail_a, mail_b))

            if offense:
                offending_peers.setdefault(mail_a, set()).add(mail_b)
                offending_peers.setdefault(mail_b, set()).add(mail_a)

        # Greedily evict the mail with the most offending pairs left, breaking ties
        # on the mail's repr for determinism, until no offending pair remains.
        evicted = set()
        while any(offending_peers.values()):
            outlier = min(
                (mail for mail, peers in offending_peers.items() if peers),
                key=lambda mail: (-len(offending_peers[mail]), repr(mail)),
            )
            evicted.add(outlier)
            offending_peers.pop(outlier)
            for peers in offending_peers.values():
                peers.discard(outlier)

        if evicted and self.size - len(evicted) < 2:
            if size_offense:
                raise SizeDiffAboveThreshold
            raise ContentDiffAboveThreshold

        return evicted

    def diff(self, mail_a: DedupMailMixin, mail_b: DedupMailMixin) -> int:
        """Return difference in bytes between two mails' normalized body.

        ```{todo}
        Rewrite the diff algorithm to not rely on naive unified diff result parsing.
        ```
        """
        return len(
            "".join(
                unified_diff(
                    mail_a.body_lines,
                    mail_b.body_lines,
                    # Ignore difference in filename lengths and timestamps.
                    fromfile="a",
                    tofile="b",
                    fromfiledate="",
                    tofiledate="",
                    n=0,
                    lineterm="\n",
                ),
            ),
        )

    def pretty_diff(self, mail_a: DedupMailMixin, mail_b: DedupMailMixin) -> str:
        """Returns a verbose unified diff between two mails' normalized body."""
        return "".join(
            unified_diff(
                mail_a.body_lines,
                mail_b.body_lines,
                fromfile=f"Normalized body of {mail_a!r}",
                tofile=f"Normalized body of {mail_b!r}",
                fromfiledate=""
                if mail_a.timestamp is None
                else f"{mail_a.timestamp:0.2f}",
                tofiledate=""
                if mail_b.timestamp is None
                else f"{mail_b.timestamp:0.2f}",
                n=0,
                lineterm="\n",
            ),
        )

    def skip_set(self, reason: str, stat: Stat) -> None:
        """Mark the entire set as skipped."""
        logging.warning(f"Skip set: {reason}")
        self.stats[Stat.MAIL_SKIPPED] += self.size
        self.stats[stat] += 1

    def select(self) -> None:
        """Settle which mails of the set are selected and which are discarded.

        Run preliminary checks, then apply the strategies to the pool of mails, each
        in turn until one produces a proper selection.

        The process results in two subsets of mails: the selected and the discarded.
        """
        # Fine-grained checks on mail differences.

        if self.size == 1:
            self.stats[Stat.SET_SINGLE] += 1
            self.stats[Stat.MAIL_UNIQUE] += 1
            self.stats[Stat.MAIL_DUPLICATES] = 0
            self.selection = set(self.pool)
            self.unique = set(self.pool)
            return

        try:
            evicted = self.check_differences()
        except UnicodeDecodeError as expt:
            logging.debug(f"{expt}")
            return self.skip_set(
                "unparsable mails due to bad encoding.", Stat.SET_SKIPPED_ENCODING
            )
        except SizeDiffAboveThreshold:
            return self.skip_set(
                "mails are too dissimilar in size.", Stat.SET_SKIPPED_SIZE
            )
        except ContentDiffAboveThreshold:
            return self.skip_set(
                "mails are too dissimilar in content.", Stat.SET_SKIPPED_CONTENT
            )

        if evicted:
            logging.warning(
                f"Set aside {len(evicted)} mails too dissimilar from the rest of "
                "the set: "
                + ", ".join(sorted(repr(mail) for mail in evicted))
                + ". Narrow down the --hash-header selection if they were expected "
                "to be recognized as copies."
            )
            self.stats[Stat.MAIL_SKIPPED] += len(evicted)
            # Resume the selection on the remaining core of coherent duplicates, and
            # invalidate the cached size so it tracks the reduced pool.
            self.pool = frozenset(self.pool.difference(evicted))
            self.__dict__.pop("size", None)

        strategies = self.conf["strategies"]
        if not strategies:
            return self.skip_set("no strategy to apply.", Stat.SET_SKIPPED_STRATEGY)

        # Fetch the subset of selected mails from the set by applying each strategy in
        # turn on the whole pool, until one achieves a proper selection. A strategy
        # failing to discriminate the set, by selecting all its mails, none of them,
        # or by missing the timestamps to compare them, hands the set over to the next
        # strategy. See: https://github.com/kdeldycke/mail-deduplicate/issues/647
        selected = set()
        skip_reason = ""
        skip_stat = Stat.SET_SKIPPED_STRATEGY
        for strategy_counter, strategy in enumerate(strategies, 1):
            skip_stat = Stat.SET_SKIPPED_STRATEGY
            try:
                selected = strategy.apply(self)
            except MissingTimestamps as expt:
                selected = set()
                skip_reason = (
                    f"the strategy cannot compare mails without a timestamp. {expt}"
                )
                skip_stat = Stat.SET_SKIPPED_TIMESTAMP
            else:
                # A strategy selecting the whole set achieves nothing.
                if len(selected) == self.size:
                    skip_reason = (
                        f"all {len(selected)} mails within were selected. "
                        "The strategy criterion was not able to discard some."
                    )
                    selected = set()
                elif not selected:
                    skip_reason = (
                        "No mail within were selected. "
                        "The strategy criterion was not able to select some."
                    )
            if selected:
                break
            if strategy_counter < len(strategies):
                logging.info(
                    f"{get_current_theme().choice(str(strategy))} strategy failed: "
                    f"{skip_reason} Fall back to the next strategy..."
                )

        # The whole cascade was exhausted without producing a proper selection.
        if not selected:
            return self.skip_set(skip_reason, skip_stat)

        candidate_count = len(selected)
        logging.debug(f"{candidate_count} mail candidates selected for action.")
        self.stats[Stat.MAIL_SELECTED] += candidate_count
        self.stats[Stat.MAIL_DISCARDED] += self.size - candidate_count
        self.stats[Stat.SET_DEDUPLICATED] += 1
        self.selection = selected
        self.discard = set(self.pool.difference(selected))


class HashedMail(NamedTuple):
    """What a hashing worker sends back for one mail.

    Deliberately nothing but scalars: the parsed message stays in the worker and dies
    with the task, so a few dozen bytes cross the process boundary instead of the
    whole mail. Which mail an answer belongs to is not carried either, as `fan_out()`
    hands every answer back alongside the task it came from. The parent rebuilds the
    same dehydrated stub it would have produced itself, exactly as it does for a mail
    restored from the cache.
    """

    mail_hash: str | None
    timestamp: float | None
    mail_size: int | None
    rejection: str | None


_WORKER: dict = {}
"""Per-process state, populated once by `_init_hash_worker()`.

Handed over at pool startup rather than with every task, so the configuration is
pickled once per worker instead of once per mail.
"""


def _init_hash_worker(conf: Config, message_class: type) -> None:
    """Prepare a worker process to hash mails of one box format."""
    _WORKER["conf"] = conf
    _WORKER["message_class"] = message_class
    _WORKER["body_hasher"] = conf["hash_body"].function


def _load_worker_mail(source_path: str, mail_id: str, path: str) -> DedupMailMixin:
    """Read and parse one mail from its own file, in a worker process.

    The mail is stamped with the identity the parent knows it by, and with the
    location it was opened from: out here there is no box to derive either from.
    """
    with open(path, "rb") as handle:
        mail = _WORKER["message_class"](handle)
    mail.source_path = source_path
    mail.mail_id = mail_id
    mail._path_override = path
    mail.conf = _WORKER["conf"]
    return mail  # type: ignore[no-any-return]


def _hash_in_worker(task: tuple[str, str, str]) -> HashedMail:
    """Read, parse and hash one mail from its own file, in a worker process.

    Only ever handed mails of folder-based boxes, which own their file, so nothing
    is shared with the other workers or with the parent. Failures come back as a
    rejection rather than an exception, so one unreadable mail cannot take the pool
    down with it.
    """
    source_path, mail_id, path = task
    try:
        mail = _load_worker_mail(source_path, mail_id, path)
    except OSError as expt:
        return HashedMail(None, None, None, f"unreadable file: {expt}")

    try:
        mail_hash = mail.hash_key() + _WORKER["body_hasher"](mail)
    except TooFewHeaders as expt:
        return HashedMail(None, None, None, expt.args[0])

    mail.dehydrate()
    return HashedMail(
        mail_hash,
        mail.__dict__.get("timestamp"),
        mail.__dict__.get("size"),
        None,
    )


class MailMeta(NamedTuple):
    """All a worker needs to rebuild one mail of a duplicate set from its own file."""

    source_path: str
    mail_id: str
    path: str
    timestamp: float | None
    mail_size: int | None


class SelectedSet(NamedTuple):
    """What a selection worker sends back for one duplicate set.

    Mails are named rather than returned: the parent already holds them, and shipping
    them back would mean pickling every message it worked so hard not to keep.
    """

    selected: tuple[tuple[str, str], ...]
    unique: tuple[tuple[str, str], ...]
    discarded: tuple[tuple[str, str], ...]
    stats: dict[Stat, int]
    records: tuple[tuple[int, str], ...]


class _RecordCollector(logging.Handler):
    """Holds onto what a worker logs, for the parent to say in its place.

    A worker's own stream goes nowhere the user can see, and several of them writing
    at once would interleave regardless. Collecting instead lets the parent replay
    each set's messages under its own heading, in the order a sequential run
    would have printed them.
    """

    def __init__(self, sink: list[tuple[int, str]]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append((record.levelno, record.getMessage()))


def _init_select_worker(conf: Config, message_class: type, log_level: int) -> None:
    """Prepare a worker process to apply the selection strategies.

    The parent's log level is handed over so a worker neither collects messages that
    would be dropped on arrival, nor spends anything building them.
    """
    _WORKER["conf"] = conf
    _WORKER["message_class"] = message_class
    logging.getLogger().setLevel(log_level)


def _name_mails(mails: Iterable[DedupMailMixin]) -> tuple[tuple[str, str], ...]:
    """Name each mail by its box and its ID, for a worker to hand back to the parent.

    Both are set the moment a mail is read from its box, which every mail a worker
    sees has been, but the attributes stay optional on the class.
    """
    return tuple((cast("str", m.source_path), cast("str", m.mail_id)) for m in mails)


def _select_in_worker(task: tuple[str, tuple[MailMeta, ...]]) -> SelectedSet:
    """Run one duplicate set through the thresholds and the selection strategies.

    Sets share nothing with each other, which is what makes this worth handing out:
    a worker re-reads only the mails of its own set, from their own files.
    """
    hash_key, metas = task

    mails = []
    for meta in metas:
        mail = _load_worker_mail(meta.source_path, meta.mail_id, meta.path)
        # Already settled by the hashing step: recomputing risks disagreeing with it.
        mail.__dict__["timestamp"] = meta.timestamp
        if meta.mail_size is not None:
            mail.__dict__["size"] = meta.mail_size
        mails.append(mail)

    captured: list[tuple[int, str]] = []
    handler = _RecordCollector(captured)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        duplicates = DuplicateSet(hash_key, mails, _WORKER["conf"])
        duplicates.select()
    finally:
        root.removeHandler(handler)

    return SelectedSet(
        selected=_name_mails(duplicates.selection),
        unique=_name_mails(duplicates.unique),
        discarded=_name_mails(duplicates.discard),
        stats=dict(duplicates.stats),
        records=tuple(captured),
    )


class Deduplicate:
    """Load-up messages, search for duplicates, apply selection strategy and perform the
    action.

    Similar messages sharing the same hash are grouped together in a `DuplicateSet`.
    """

    CHUNK_SIZE: int = 200
    """Mails handed to a hashing worker in one go.

    Each queue round-trip costs far more than hashing a single mail, so tasks travel
    in chunks. Large enough to make that cost disappear, small enough that the last
    worker to finish does not hold up the others.
    """

    SET_CHUNK_SIZE: int = 32
    """Duplicate sets handed to a selection worker in one go.

    Smaller than the hashing chunk because a set is several mails' worth of work, so
    fewer of them already amortize the same round-trip.
    """

    def __init__(self, conf: Config) -> None:
        self.sources: dict[str, Mailbox] = {}
        """Index of mail sources by their full, normalized path. So we can refer
        to them in Mail instances. Also have the nice side effect of natural
        deduplication of sources themselves.
        """

        self.mails: dict[str, list[DedupMailMixin]] = {}
        """All mails grouped by hashes.

        Grouped in lists rather than sets: mails carry no value equality, so a set
        only ever deduplicated by object identity, which the single pass over each
        box already rules out. A one-element list also costs 64 bytes where a set
        costs 216, and most hashes group a single mail.
        """

        self.selection: set[DedupMailMixin] = set()
        """Mails selected after application of selection strategy."""

        self.unique: set[DedupMailMixin] = set()
        """The subset of the selection made of mails that have no duplicate.

        See `DuplicateSet.unique`, which each duplicate set contributes here.
        """

        self.discard: set[DedupMailMixin] = set()
        """Mails discarded after application of selection strategy."""

        self.link_targets: dict[DedupMailMixin, DedupMailMixin] = {}
        """Maps each discarded mail to the selected mail it can be hardlinked to.

        Left empty unless the configured action consumes it: see
        `track_link_targets`.
        """

        self.conf = conf
        """Configuration shared across the deduplication process."""

        self.track_link_targets: bool = conf["action"].verb == "hardlink"
        """Whether each discarded mail has to be paired with a selected one.

        Only the hardlinking action needs that pairing, and it costs one dictionary
        entry per discarded mail, so it is settled once here and only recorded when
        something reads it.
        """

        self.stats: Counter[Stat] = Counter()
        """Deduplication statistics. Unset statistics naturally read as zero."""

        self.cache: HashCache | None = open_cache(conf)
        """Cross-run cache of mail hashes, when the user opted in with `--cache` and
        the database could be opened."""

    def restore_cached(
        self, box: Mailbox, mail_id: str, entry: CacheEntry
    ) -> tuple[DedupMailMixin, str, None]:
        """Rebuild a hashed mail from its cache entry, without opening its file.

        Produces the same dehydrated stub the hashing step would have left behind,
        with the scalars the later steps rely on already memoized. Anything else
        those steps need is re-read from the box on demand, as for any other mail.
        """
        mail = self.blank_stub(box, mail_id)
        # A ctime timestamp is a stat away and would not be caught by the cache's
        # staleness key, so it is left to be derived rather than restored.
        if self.conf["time_source"] != TimeSource.CTIME:
            mail.__dict__["timestamp"] = entry.timestamp
        if entry.mail_size is not None:
            mail.__dict__["size"] = entry.mail_size
        mail.dehydrate()
        return mail, entry.mail_hash, None

    def blank_stub(self, box: Mailbox, mail_id: str) -> DedupMailMixin:
        """An empty mail carrying only its identity, ready to be filled in.

        Stands in for a mail this process never parsed, because its content came
        from the cache or from a worker that has already thrown it away.
        """
        factory = cast("Callable[[], DedupMailMixin]", box._factory)
        mail = factory()
        mail.add_box_metadata(box, mail_id)
        mail.conf = self.conf
        return mail

    def parallel_boxes(self) -> list[Mailbox]:
        """The sources whose mails a worker process could hash on its own.

        Only folder-based boxes qualify. Their mails each own a file, which a worker
        opens by path, sharing nothing. Mails of a file-based box are byte ranges of
        one file that a single handle seeks through, so handing them out would mean
        several processes seeking the same descriptor.

        Returns an empty list unless *every* source qualifies, so a run is either
        wholly parallel or wholly sequential rather than silently half of each.
        """
        boxes = list(self.sources.values())
        if boxes and all(isinstance(box, FOLDER_FORMAT_CLASSES) for box in boxes):
            return boxes
        return []

    @property
    def jobs(self) -> int:
        """Worker processes the `--jobs` option resolved to, read off the context."""
        return cast("int", context.get(get_current_context(), context.JOBS, 1))

    @contextmanager
    def worker_pool(
        self,
        jobs: int,
        initializer: Callable,
        initargs: tuple,
        verb: str,
        doing: str,
    ) -> Iterator[ProcessPoolExecutor | None]:
        """Hand out a pool of worker processes prepared by the initializer, and shut
        it down however the block it wraps ends.

        Yields `None` instead when the pool cannot be started, which is the case in
        some frozen or sandboxed environments: the initializer is then run right
        here, so the worker functions find the state they expect, and the caller
        degrades to sequential calls instead of dying.
        """
        pool: ProcessPoolExecutor | None = None
        try:
            pool = ProcessPoolExecutor(
                max_workers=jobs,
                initializer=initializer,
                initargs=initargs,
            )
        except (OSError, ValueError, ImportError, NotImplementedError) as expt:
            logging.warning(f"Cannot start {jobs} {doing} processes: {expt}")
            logging.warning(f"{verb} in this process instead.")
            initializer(*initargs)
        else:
            logging.info(f"{verb} mails across {jobs} processes.")

        try:
            yield pool
        finally:
            if pool is not None:
                pool.shutdown()

    def fan_out(
        self,
        pool: ProcessPoolExecutor | None,
        worker: Callable,
        tasks: Iterable[tuple],
        window: int,
        chunksize: int,
    ) -> Iterator[tuple]:
        """Yields each task back alongside its worker's answer.

        Tasks pair what the parent keeps with the payload its worker receives, and
        are handed out a window at a time rather than all at once: `map()` consumes
        whatever it is given immediately, so passing the whole corpus would hold a
        task per mail, undoing the flat memory the rest of the run maintains. The
        window is wide enough that every worker always has chunks queued behind it.

        With or without a pool, answers come back in submission order, so whatever
        the caller aggregates comes out identical to a sequential run at any number
        of workers.
        """
        stream = iter(tasks)
        while batch := list(islice(stream, window)):
            payloads = [payload for _, payload in batch]
            if pool is None:
                results: Iterable = map(worker, payloads)
            else:
                # Chunked so a queue round-trip is amortized over many payloads.
                results = pool.map(worker, payloads, chunksize=chunksize)
            yield from zip((kept for kept, _ in batch), results)

    def uncached(
        self, boxes: Iterable[Mailbox], absorb: Callable, progress
    ) -> Iterator[tuple[Mailbox, str]]:
        """Yields the identity of every mail the cache cannot answer for.

        A mail the cache can restore is absorbed here and never even opened, which
        is the whole point of keeping the cache. Lazy, and driven from the main
        process alone: neither box objects nor the cache are safe for concurrent
        access.
        """
        for box in boxes:
            for mail_id in iter_mail_ids(box):
                entry = self.cache.lookup(box, mail_id) if self.cache else None
                if entry is not None:
                    absorb(self.restore_cached(box, mail_id, entry))
                    progress.update(1)
                    continue
                yield box, mail_id

    def hash_in_parallel(self, jobs: int, absorb: Callable, progress) -> None:
        """Hash every uncached mail across a pool of worker processes.

        Threads cannot do this job: what hashing spends itself on is Python-level
        work that the interpreter lock serializes, so fanning it out across threads
        only adds contention. Processes sidestep the lock, and the mail never has to
        travel: a worker opens its own file and sends back a hash and two scalars.
        """
        boxes = self.parallel_boxes()
        # Every source shares one structure, checked by parallel_boxes(), so a single
        # worker setup serves them all.
        factory = cast("type", boxes[0]._factory)

        def tasks():
            """Pairs each pending mail with the task handed to its worker."""
            for box, mail_id in self.uncached(boxes, absorb, progress):
                yield (
                    (box, mail_id),
                    (box._path, mail_id, resolve_mail_path(box, mail_id)),
                )

        with self.worker_pool(
            jobs, _init_hash_worker, (self.conf, factory), "Hash", "hashing"
        ) as pool:
            for (box, mail_id), result in self.fan_out(
                pool,
                _hash_in_worker,
                tasks(),
                jobs * self.CHUNK_SIZE * 4,
                self.CHUNK_SIZE,
            ):
                absorb(self.adopt_hashed(box, mail_id, result))
                progress.update(1)

    def adopt_hashed(
        self, box: Mailbox, mail_id: str, result: HashedMail
    ) -> tuple[DedupMailMixin, str | None, TooFewHeaders | None]:
        """Turn a worker's answer back into the mail stub this process works with."""
        if result.rejection is not None:
            return self.blank_stub(box, mail_id), None, TooFewHeaders(result.rejection)
        return self.restore_cached(
            box,
            mail_id,
            CacheEntry(
                cast("str", result.mail_hash), result.timestamp, result.mail_size
            ),
        )

    def add_source(self, source_path: Path | str) -> None:
        """Registers a source of mails, validates and opens it.

        Duplicate sources of mails are not allowed, as when we perform the action, we
        use the path as a unique key to tie back a mail from its source.
        """
        # Make the path absolute and resolve any symlinks.
        path = Path(source_path).resolve(strict=True)
        if str(path) in self.sources:
            raise ValueError(f"{path} already added.")

        # Open and register the mail source. Subfolders will be registered as their
        # own box.
        boxes = open_box(path, self.conf["input_format"], self.conf["force_unlock"])
        for box in boxes:
            self.sources[box._path] = box

            # Track global mail count.
            mail_found = len(box)
            logging.info(f"{mail_found} mails found.")
            self.stats[Stat.MAIL_FOUND] += mail_found

    def hash_all(self) -> None:
        """Browse all mails from all registered sources, compute hashes and group mails
        by hash.

        Displays a progress bar as the operation might be slow.

        Each mail is dehydrated as soon as it is hashed, so whatever the size of the
        corpus, only a lightweight stub of every mail is retained. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/761

        Hashing fans out across worker processes when `--jobs` resolves above 1 and
        every source is a folder-based box; otherwise mails stream through this
        process one at a time, which is also the lowest-memory path. Box listing and
        the hash cache always stay in this process, as neither is safe for
        concurrent access, so the speedup is largest where the hashing itself is the
        cost, with `--hash-body raw`/`normalized`.
        """
        theme = get_current_theme()
        logging.info(
            f"Use [{', '.join(map(theme.choice, self.conf['hash_headers']))}] headers to "
            "compute hashes.",
        )

        body_hasher = self.conf["hash_body"].function

        def compute(box, mail_id, mail):
            """Hash a single parsed mail, in this very process.

            The mail is dehydrated on the way out, so only its identity and memoized
            scalars survive the hashing step.
            """
            mail.add_box_metadata(box, mail_id)
            mail.conf = self.conf
            try:
                return mail, mail.hash_key() + body_hasher(mail), None
            except TooFewHeaders as expt:
                return mail, None, expt
            finally:
                mail.dehydrate()

        def absorb(result):
            """Merge one hashed mail into the shared groups and stats. Called only from
            the main process, keeping the parallel path and the cache race-free."""
            mail, mail_hash, expt = result
            if expt is not None:
                logging.warning(f"Rejecting {mail!r}: {expt.args[0]}")
                self.stats[Stat.MAIL_REJECTED] += 1
                if self.cache:
                    # A rejection depends on more than the hash, so it is not cached.
                    self.cache.forget(mail.source_path, mail.mail_id)
            else:
                self.mails.setdefault(mail_hash, []).append(mail)
                self.stats[Stat.MAIL_RETAINED] += 1
                if self.cache:
                    self.cache.store(
                        mail.source_path,
                        mail.mail_id,
                        CacheEntry(
                            mail_hash,
                            mail.__dict__.get("timestamp"),
                            mail.__dict__.get("size"),
                        ),
                    )

        jobs = self.jobs

        with progressbar(
            length=self.stats[Stat.MAIL_FOUND],
            label="Hashed mails",
            show_pos=True,
        ) as progress:
            if jobs > 1 and self.parallel_boxes():
                self.hash_in_parallel(jobs, absorb, progress)
            else:
                # Stream one mail at a time: only the mail in flight is ever parsed.
                for box, mail_id in self.uncached(
                    self.sources.values(), absorb, progress
                ):
                    try:
                        mail = box[mail_id]
                    except KeyError:
                        # The mail went away between the box listing it and us
                        # reading it, which `iteritems()` also skips over.
                        logging.debug(f"Mail {mail_id} vanished from {box._path}.")
                        continue
                    absorb(compute(box, mail_id, mail))
                    progress.update(1)

        if self.cache:
            # One transaction for the whole step, so an interrupted run leaves the
            # database as it found it.
            self.cache.commit()
            summary = (
                f"Hash cache: {self.cache.hits} mails restored, "
                f"{self.cache.misses} hashed and recorded"
            )
            if self.cache.pruned:
                summary += f", {self.cache.pruned} stale entries dropped"
            logging.info(f"{summary}.")

        self.stats[Stat.MAIL_HASHES] += len(self.mails)

    def build_sets(self) -> None:
        """Build the selected and discarded sets from each duplicate set.

        The selection is settled one duplicate set at a time, to keep the memory
        footprint low and make the log easier to read.
        """
        theme = get_current_theme()
        strategies = self.conf["strategies"]
        if strategies:
            logging.info(
                f"{', '.join(theme.choice(str(s)) for s in strategies)} "
                f"{'strategies' if len(strategies) > 1 else 'strategy'} will be "
                "applied on each duplicate set to select candidates.",
            )
        else:
            logging.warning("No strategy configured, skip selection.")

        # Said once here rather than per set: which thresholds are in force is a
        # property of the run, and repeating it for every duplicate set buried the
        # log under thousands of copies of the same two sentences.
        if self.conf["size_threshold"] < 0:
            logging.info("Skip checking for size differences.")
        if self.conf["content_threshold"] < 0:
            logging.info("Skip checking for content differences.")

        self.stats[Stat.SET_TOTAL] = len(self.mails)

        jobs = self.jobs
        # Sets are announced individually at debug level only, so a plain run needs
        # something to watch: this step re-reads mails and is the longest one left
        # once the hashes come from the cache.
        with progressbar(
            length=len(self.mails),
            label="Deduplicated sets",
            show_pos=True,
        ) as progress:
            if jobs > 1 and self.parallel_boxes():
                self.select_in_parallel(jobs, progress)
                return

            for hash_key, mail_set in self.mails.items():
                self.settle(hash_key, mail_set)
                progress.update(1)

    def settle(self, hash_key: str, mail_set: list[DedupMailMixin]) -> None:
        """Run one duplicate set through the thresholds and the strategies, right in
        this process, and merge its verdict into the run."""
        self.log_set_heading(hash_key, len(mail_set))
        duplicates = DuplicateSet(hash_key, mail_set, self.conf)
        duplicates.select()
        self.stats += duplicates.stats
        self.selection.update(duplicates.selection)
        self.unique.update(duplicates.unique)
        self.discard.update(duplicates.discard)
        self.record_link_targets(duplicates.selection, duplicates.discard)
        self.release(mail_set)

    def log_set_heading(self, hash_key: str, mail_count: int) -> None:
        """Announce a duplicate set, at a level reflecting whether it holds copies.

        Styling the heading is not free, and most sets hold a single mail and so
        report at debug level, where the result is thrown away: only pay for it when
        it is actually logged.
        """
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(
                get_current_theme().subheading(
                    f"◼ {mail_count} mails sharing hash {hash_key}"
                )
            )

    def release(self, mail_set: list[DedupMailMixin]) -> None:
        """Drop the content the thresholds and strategies pulled back from the boxes.

        Iterating on the original set covers skipped sets and set-aside mails too,
        which land in neither selection nor discard.
        See: https://github.com/kdeldycke/mail-deduplicate/issues/362
        """
        for mail in mail_set:
            mail.dehydrate()

    def record_link_targets(
        self,
        selection: Iterable[DedupMailMixin],
        discard: Iterable[DedupMailMixin],
    ) -> None:
        """Pair every discarded mail of a set with a selected mail of that same set.

        Hardlinking a discarded mail only makes sense against a copy that survives
        the very set both were found in, and that pairing is the one thing the flat
        selection and discard sets no longer say once every set has been settled.

        A strategy is free to keep several mails, so the target is the one with the
        lowest path: a run then links to the same copy however the sets came back,
        which matters when the selection is spread over a pool of processes.

        Iterables are only walked once the run is known to need them, so a call from
        a non-hardlinking run costs nothing beyond the arguments themselves.
        """
        if not self.track_link_targets:
            return

        kept = tuple(selection)
        discarded = tuple(discard)
        # A skipped set discards nothing, and a set that discards always keeps at
        # least one mail to discard it against.
        if not kept or not discarded:
            return

        target = min(kept, key=lambda mail: (mail.path, str(mail.mail_id)))
        for mail in discarded:
            self.link_targets[mail] = target

    def select_in_parallel(self, jobs: int, progress) -> None:
        """Apply the selection to every duplicate set across a pool of processes.

        Duplicate sets share nothing with one another, so a set is the natural unit
        of work. Only sets holding copies are handed out: a set of one is settled
        without reading anything, and would cost more to ship than to decide.
        """
        boxes = self.parallel_boxes()
        factory = cast("type", boxes[0]._factory)
        level = logging.getLogger().getEffectiveLevel()

        def tasks():
            """Pairs each set worth handing out with its payload, settling the rest
            on the way."""
            for hash_key, mail_set in self.mails.items():
                if len(mail_set) < 2:
                    self.settle(hash_key, mail_set)
                    progress.update(1)
                    continue
                yield (
                    (hash_key, mail_set),
                    (hash_key, tuple(self.describe(mail) for mail in mail_set)),
                )

        with self.worker_pool(
            jobs,
            _init_select_worker,
            (self.conf, factory, level),
            "Select",
            "selection",
        ) as pool:
            for (hash_key, mail_set), result in self.fan_out(
                pool,
                _select_in_worker,
                tasks(),
                jobs * self.SET_CHUNK_SIZE * 2,
                self.SET_CHUNK_SIZE,
            ):
                self.adopt_selection(hash_key, mail_set, result)
                progress.update(1)

    def describe(self, mail: DedupMailMixin) -> MailMeta:
        """Everything a worker needs to rebuild a mail, and nothing more."""
        return MailMeta(
            cast("str", mail.source_path),
            cast("str", mail.mail_id),
            mail.path,
            mail.__dict__.get("timestamp"),
            mail.__dict__.get("size"),
        )

    def adopt_selection(
        self,
        hash_key: str,
        mail_set: list[DedupMailMixin],
        result: SelectedSet,
    ) -> None:
        """Merge a worker's verdict on one set back into this process.

        The heading and the worker's own messages are said here, in that order, so
        the log reads as it would have from a sequential run however the sets were
        spread out.
        """
        self.log_set_heading(hash_key, len(mail_set))
        for levelno, message in result.records:
            logging.log(levelno, message)

        # Mail IDs only identify a mail within its own box, and a duplicate set can
        # span several.
        by_id = {(mail.source_path, mail.mail_id): mail for mail in mail_set}
        self.selection.update(by_id[key] for key in result.selected)
        self.unique.update(by_id[key] for key in result.unique)
        self.discard.update(by_id[key] for key in result.discarded)
        self.record_link_targets(
            (by_id[key] for key in result.selected),
            (by_id[key] for key in result.discarded),
        )
        self.stats += Counter(result.stats)
        self.release(mail_set)

    def close_all(self) -> None:
        """Close all open boxes, and the hash cache if one was opened."""
        for source_path, box in self.sources.items():
            logging.debug(f"Close {source_path}")
            box.close()
        if self.cache:
            self.cache.close()

    def report(self) -> str:
        """Returns a text report of user-friendly statistics and metrics."""
        ctx = get_current_context()
        render_table = ctx.find_root().render_table  # type: ignore[attr-defined]

        output = ""
        for category, title in (("mail", "Mails"), ("set", "Duplicate sets")):
            table = [
                [
                    stat.name
                    .removeprefix(f"{category.upper()}_")
                    .replace("_", " - ")
                    .title(),
                    self.stats[stat],
                    stat.description,
                ]
                for stat in Stat
                if stat.category == category
            ]
            # Only the renderer knows whether wrapping applies: pre-wrapping the
            # descriptions here would bake line breaks into the cells of the
            # structured formats, and break the `vertical` layout.
            output += render_table(
                table,
                headers=(title, "Metric", "Description"),
                max_column_widths=(None, None, "auto"),
            )
            output += "\n"
        return output

    def assert_stats(
        self,
        first: Stat | tuple[Stat, ...],
        operator: str,
        second: Stat | tuple[Stat, ...],
    ) -> None:
        """Render failed stats assertions in plain English."""

        def get_value_and_name(operand: Stat | tuple[Stat, ...]) -> tuple[int, str]:
            if isinstance(operand, tuple):
                return (
                    sum(self.stats[s] for s in operand),
                    " + ".join(s.name.lower() for s in operand),
                )
            return self.stats[operand], operand.name.lower()

        first_value, first_name = get_value_and_name(first)
        second_value, second_name = get_value_and_name(second)

        match operator:
            case ">=":
                passed = first_value >= second_value
            case "==":
                passed = first_value == second_value
            case _:
                passed = False

        if passed:
            return

        logging.warning(
            "Metrics appear inconsistent.\n"
            + f"EXPECTED: {first_name} {operator} {second_name}\n"
            + f"          {first_value} {operator} {second_value}\n"
        )
        sys.exit(115)

    def check_stats(self):
        """Perform some high-level consistency checks on metrics.

        Helps users reports tricky edge-cases.
        """
        # Box opening stats.
        self.assert_stats(Stat.MAIL_FOUND, ">=", Stat.MAIL_REJECTED)
        self.assert_stats(Stat.MAIL_FOUND, ">=", Stat.MAIL_RETAINED)
        self.assert_stats(
            Stat.MAIL_FOUND, "==", (Stat.MAIL_REJECTED, Stat.MAIL_RETAINED)
        )

        # Mail grouping by hash.
        self.assert_stats(Stat.MAIL_RETAINED, ">=", Stat.MAIL_UNIQUE)
        self.assert_stats(Stat.MAIL_RETAINED, ">=", Stat.MAIL_DUPLICATES)
        self.assert_stats(
            Stat.MAIL_RETAINED, "==", (Stat.MAIL_UNIQUE, Stat.MAIL_DUPLICATES)
        )

        # Mail selection stats.
        self.assert_stats(Stat.MAIL_RETAINED, ">=", Stat.MAIL_SKIPPED)
        self.assert_stats(Stat.MAIL_RETAINED, ">=", Stat.MAIL_DISCARDED)
        self.assert_stats(Stat.MAIL_RETAINED, ">=", Stat.MAIL_SELECTED)

        self.assert_stats(
            Stat.MAIL_RETAINED,
            "==",
            (
                Stat.MAIL_UNIQUE,
                Stat.MAIL_SKIPPED,
                Stat.MAIL_DISCARDED,
                Stat.MAIL_SELECTED,
            ),
        )

        # Action stats. Each action targets a single subset of mails: the union of
        # unique and selected mails for *-selected actions, the selected ones alone
        # for the deletion sparing the mails that have no duplicate, and the
        # discarded mails for *-discarded ones. The counters the action reports on
        # are expected to account for its target exactly, as they are incremented in
        # dry-run mode too.
        action = self.conf["action"]
        if action.verb == "hardlink":
            # Hardlinking is the one action that cannot always go through: a mail
            # packed into a file-based box, one already sharing its copy's inode and
            # one sitting on another filesystem are all left alone. So the discarded
            # mails are accounted for by both outcomes together, not by the linked
            # ones alone.
            self.assert_stats(
                Stat.MAIL_DISCARDED,
                "==",
                (Stat.MAIL_HARDLINKED, Stat.MAIL_HARDLINK_SKIPPED),
            )
        else:
            action_counter = {
                "copy": Stat.MAIL_COPIED,
                "move": Stat.MAIL_MOVED,
                "delete": Stat.MAIL_DELETED,
            }[action.verb]
            if action.acts_on_discarded:
                self.assert_stats(Stat.MAIL_DISCARDED, "==", action_counter)
            elif action.spares_unique:
                self.assert_stats(Stat.MAIL_SELECTED, "==", action_counter)
            else:
                self.assert_stats(
                    (Stat.MAIL_UNIQUE, Stat.MAIL_SELECTED), "==", action_counter
                )

        # Sets accounting.
        self.assert_stats(Stat.SET_TOTAL, "==", Stat.MAIL_HASHES)
        self.assert_stats(Stat.SET_SINGLE, "==", Stat.MAIL_UNIQUE)
        self.assert_stats(
            Stat.SET_TOTAL,
            "==",
            (
                Stat.SET_SINGLE,
                Stat.SET_SKIPPED_ENCODING,
                Stat.SET_SKIPPED_SIZE,
                Stat.SET_SKIPPED_CONTENT,
                Stat.SET_SKIPPED_TIMESTAMP,
                Stat.SET_SKIPPED_STRATEGY,
                Stat.SET_DEDUPLICATED,
            ),
        )
