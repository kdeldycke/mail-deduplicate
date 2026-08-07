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

import logging
import sys
import textwrap
from collections import Counter
from difflib import unified_diff
from enum import Enum
from functools import cached_property
from itertools import combinations, islice
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple, cast

from click_extra import (
    context,
    get_current_context,
    get_current_theme,
    progressbar,
    run_jobs,
)

from .cache import CacheEntry, HashCache, open_cache
from .mail import TimeSource, TooFewHeaders
from .mail_box import open_box

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from mailbox import Mailbox

    from .cli import Config
    from .mail import DedupMailMixin


class StatDef(NamedTuple):
    """Definition of a statistic with its description and category."""

    description: str
    category: str  # "mail" or "set"


class Stat(Enum):
    """All tracked statistics and their definition."""

    MAIL_FOUND = StatDef(
        "Total number of mails encountered from all mail sources.", "mail"
    )
    MAIL_REJECTED = StatDef(
        "Number of mails rejected individually because they were unparsable or "
        "did not have enough metadata to compute hashes.",
        "mail",
    )
    MAIL_RETAINED = StatDef(
        "Number of valid mails parsed and retained for deduplication.", "mail"
    )
    MAIL_HASHES = StatDef("Number of unique hashes.", "mail")
    MAIL_UNIQUE = StatDef(
        "Number of unique mails (which were automatically added to selection).", "mail"
    )
    MAIL_DUPLICATES = StatDef(
        "Number of duplicate mails (sum of mails in all duplicate sets with at "
        "least 2 mails).",
        "mail",
    )
    MAIL_SKIPPED = StatDef(
        "Number of mails ignored in the selection step because the whole set "
        "they belong to was skipped.",
        "mail",
    )
    MAIL_DISCARDED = StatDef(
        "Number of mails discarded from the final selection.", "mail"
    )
    MAIL_SELECTED = StatDef(
        "Number of mails kept in the final selection on which the "
        "action will be performed.",
        "mail",
    )
    MAIL_COPIED = StatDef(
        "Number of mails copied from their original mailbox to another.", "mail"
    )
    MAIL_MOVED = StatDef(
        "Number of mails moved from their original mailbox to another.", "mail"
    )
    MAIL_DELETED = StatDef(
        "Number of mails deleted from their mailbox in-place.", "mail"
    )
    SET_TOTAL = StatDef("Total number of duplicate sets.", "set")
    SET_SINGLE = StatDef(
        "Total number of sets containing only a single mail with no applicable "
        "strategy. They were automatically kept in the final selection.",
        "set",
    )
    SET_SKIPPED_ENCODING = StatDef(
        "Number of sets skipped from the selection process because they had "
        "encoding issues.",
        "set",
    )
    SET_SKIPPED_SIZE = StatDef(
        "Number of sets skipped from the selection process because they were "
        "too dissimilar in size.",
        "set",
    )
    SET_SKIPPED_CONTENT = StatDef(
        "Number of sets skipped from the selection process because they were "
        "too dissimilar in content.",
        "set",
    )
    SET_SKIPPED_TIMESTAMP = StatDef(
        "Number of sets skipped from the selection process because a timestamp "
        "could not be derived for some of their mails.",
        "set",
    )
    SET_SKIPPED_STRATEGY = StatDef(
        "Number of sets skipped from the selection process because the strategy "
        "could not be applied.",
        "set",
    )
    SET_DEDUPLICATED = StatDef(
        "Number of valid sets on which the selection strategy was successfully "
        "applied.",
        "set",
    )

    @property
    def description(self) -> str:
        """Returns the description of the statistic."""
        return self.value.description

    @property
    def category(self) -> str:
        """Returns the category of the statistic ('mail' or 'set')."""
        return self.value.category


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

    def hash_function(self):
        """Returns the hashing function corresponding to the body hasher."""
        return {
            BodyHasher.SKIP: lambda _: "",
            BodyHasher.RAW: lambda m: m.hash_raw_body,
            BodyHasher.NORMALIZED: lambda m: m.hash_normalized_body,
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
    def newest_timestamp(self):
        """Returns the newest timestamp among all mails in the set."""
        return max(self.timestamps)

    @cached_property
    def oldest_timestamp(self):
        """Returns the oldest timestamp among all mails in the set."""
        return min(self.timestamps)

    @cached_property
    def biggest_size(self):
        """Returns the biggest size among all mails in the set."""
        return max(map(attrgetter("size"), self.pool))

    @cached_property
    def smallest_size(self):
        """Returns the smallest size among all mails in the set."""
        return min(map(attrgetter("size"), self.pool))

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

        logging.info("Check mail differences are below the thresholds.")
        if size_threshold < 0:
            logging.info("Skip checking for size differences.")
        if content_threshold < 0:
            logging.info("Skip checking for content differences.")
        if size_threshold < 0 and content_threshold < 0:
            return set()

        # Adjacency of mails linked by a pair exceeding a threshold.
        offending_peers: dict[DedupMailMixin, set[DedupMailMixin]] = {}
        size_offense = False
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
                content_difference = self.diff(mail_a, mail_b)
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
            outlier = sorted(
                (mail for mail, peers in offending_peers.items() if peers),
                key=lambda mail: (-len(offending_peers[mail]), repr(mail)),
            )[0]
            evicted.add(outlier)
            offending_peers.pop(outlier)
            for peers in offending_peers.values():
                peers.discard(outlier)

        if evicted and self.size - len(evicted) < 2:
            if size_offense:
                raise SizeDiffAboveThreshold
            raise ContentDiffAboveThreshold

        return evicted

    def diff(self, mail_a, mail_b):
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

    def pretty_diff(self, mail_a, mail_b):
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

    def categorize_candidates(self):
        """Process the list of duplicates for action.

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
                selected = strategy.apply_strategy(self)
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
        logging.info(f"{candidate_count} mail candidates selected for action.")
        self.stats[Stat.MAIL_SELECTED] += candidate_count
        self.stats[Stat.MAIL_DISCARDED] += self.size - candidate_count
        self.stats[Stat.SET_DEDUPLICATED] += 1
        self.selection = selected
        self.discard = set(self.pool.difference(selected))


class Deduplicate:
    """Load-up messages, search for duplicates, apply selection strategy and perform the
    action.

    Similar messages sharing the same hash are grouped together in a `DuplicateSet`.
    """

    PARALLEL_BATCH_FACTOR: int = 8
    """Number of mails, per job, materialized at once by the parallel hashing path.

    Parsed mails are only held for the batch in flight, instead of the whole corpus,
    keeping the memory footprint of `--jobs` runs bounded. The factor is large
    enough to amortize the per-batch synchronization, small enough to keep memory
    flat.
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

        self.discard: set[DedupMailMixin] = set()
        """Mails discarded after application of selection strategy."""

        self.conf = conf
        """Configuration shared across the deduplication process."""

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
        factory = cast("Callable[[], DedupMailMixin]", box._factory)
        mail = factory()
        mail.add_box_metadata(box, mail_id)
        mail.conf = self.conf
        # A ctime timestamp is a stat away and would not be caught by the cache's
        # staleness key, so it is left to be derived rather than restored.
        if self.conf["time_source"] != TimeSource.CTIME:
            mail.__dict__["timestamp"] = entry.timestamp
        if entry.mail_size is not None:
            mail.__dict__["size"] = entry.mail_size
        mail.dehydrate()
        return mail, entry.mail_hash, None

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

    def hash_all(self):
        """Browse all mails from all registered sources, compute hashes and group mails
        by hash.

        Displays a progress bar as the operation might be slow.

        Each mail is dehydrated as soon as it is hashed, so whatever the size of the
        corpus, only a lightweight stub of every mail is retained. See:
        https://github.com/kdeldycke/mail-deduplicate/issues/761

        Hashing fans out across worker threads when `--jobs` resolves above 1; at
        the default of a single job, mails stream through one at a time. Mail reading
        always stays single-threaded because `mailbox` box objects are not safe for
        concurrent access: only the CPU-bound hashing is parallelized, in batches
        bounding the number of parsed mails in flight, so the speedup is largest with
        `--hash-body raw`/`normalized`.
        """
        theme = get_current_theme()
        logging.info(
            f"Use [{', '.join(map(theme.choice, self.conf['hash_headers']))}] headers to "
            "compute hashes.",
        )

        body_hasher = self.conf["hash_body"].hash_function()

        def compute(item):
            """Hash a single mail. Pure per-mail work, safe in a worker thread: it only
            touches its own mail and the read-only shared config. The mail is
            dehydrated on the way out, so only its identity and memoized scalars
            survive the hashing step."""
            box, mail_id, mail = item
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
            the main thread, keeping the parallel path and the cache race-free."""
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

        jobs = context.get(get_current_context(), context.JOBS, 1)

        with progressbar(
            length=self.stats[Stat.MAIL_FOUND],
            label="Hashed mails",
            show_pos=True,
        ) as progress:
            def to_hash():
                """Yields the mails still needing to be hashed.

                Lazy and single-threaded: neither box objects nor the cache are
                concurrency-safe, and only the mails in flight are ever parsed. A
                mail the cache can restore is absorbed here and never even opened,
                which is the whole point of keeping the cache.
                """
                for box in self.sources.values():
                    for mail_id in box.iterkeys():
                        entry = self.cache.lookup(box, mail_id) if self.cache else None
                        if entry is not None:
                            absorb(self.restore_cached(box, mail_id, entry))
                            progress.update(1)
                            continue
                        try:
                            mail = box[mail_id]
                        except KeyError:
                            # The mail went away between the box listing it and us
                            # reading it, which `iteritems()` also skips over.
                            logging.debug(f"Mail {mail_id} vanished from {box._path}.")
                            continue
                        yield box, mail_id, mail

            stream = to_hash()
            if jobs <= 1:
                # Stream one mail at a time: lowest memory, progress tracks each read.
                for item in stream:
                    absorb(compute(item))
                    progress.update(1)
            else:
                # Parallel-hash in bounded batches: `run_jobs` materializes whatever
                # it is handed, so only one batch of parsed mails exists at a time,
                # and each mail shrinks to its dehydrated form as soon as it is
                # hashed. `run_jobs` yields in submission order, so grouping and
                # stats stay deterministic regardless of the job count.
                batch_size = jobs * self.PARALLEL_BATCH_FACTOR
                while batch := list(islice(stream, batch_size)):
                    for result in run_jobs(compute, batch, jobs=jobs):
                        absorb(result)
                        progress.update(1)

        if self.cache:
            # One transaction for the whole step, so an interrupted run leaves the
            # database as it found it.
            self.cache.commit()
            logging.info(
                f"Hash cache: {self.cache.hits} mails restored, "
                f"{self.cache.misses} hashed and recorded.",
            )

        self.stats[Stat.MAIL_HASHES] += len(self.mails)

    def build_sets(self):
        """Build the selected and discarded sets from each duplicate set.

        We apply the selection strategy one duplicate set at a time to keep memory
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

        self.stats[Stat.SET_TOTAL] = len(self.mails)

        for hash_key, mail_set in self.mails.items():
            # Alter log level depending on set length.
            mail_count = len(mail_set)
            log_level = logging.debug if mail_count == 1 else logging.info
            log_level(theme.subheading(f"◼ {mail_count} mails sharing hash {hash_key}"))

            # Apply the selection strategy to discriminate mails within the set.
            duplicates = DuplicateSet(hash_key, mail_set, self.conf)
            duplicates.categorize_candidates()
            # Merge duplicate set's stats to global stats.
            self.stats += duplicates.stats
            self.selection.update(duplicates.selection)
            self.discard.update(duplicates.discard)

            # Dehydrate the whole set to release the content re-read from the
            # source boxes by the thresholds and strategies. Iterating on the
            # original set covers skipped sets and set-aside mails too, which land
            # in neither selection nor discard.
            # See: https://github.com/kdeldycke/mail-deduplicate/issues/362
            for mail in mail_set:
                mail.dehydrate()

    def close_all(self):
        """Close all open boxes, and the hash cache if one was opened."""
        for source_path, box in self.sources.items():
            logging.debug(f"Close {source_path}")
            box.close()
        if self.cache:
            self.cache.close()

    def report(self):
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
                    "\n".join(textwrap.wrap(stat.description, 60)),
                ]
                for stat in Stat
                if stat.category == category
            ]
            output += render_table(table, headers=(title, "Metric", "Description"))
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
        # unique and selected mails for *-selected actions, the discarded mails for
        # *-discarded ones. The action's counter is expected to match its target
        # exactly, as counters are also incremented in dry-run mode.
        action_id = str(self.conf["action"])
        action_counter = {
            "copy": Stat.MAIL_COPIED,
            "move": Stat.MAIL_MOVED,
            "delete": Stat.MAIL_DELETED,
        }[action_id.split("-")[0]]
        if action_id.endswith("-discarded"):
            self.assert_stats(Stat.MAIL_DISCARDED, "==", action_counter)
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
