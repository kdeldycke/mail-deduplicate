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
from itertools import combinations
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple

from click_extra import get_current_context, progressbar
from click_extra.colorize import default_theme as theme

from .mail import TooFewHeaders
from .mail_box import open_box

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum  # type: ignore[import-not-found]

TYPE_CHECKING = False
if TYPE_CHECKING:
    from mailbox import Mailbox, Message

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


class Stats:
    """Type-safe statistics counter using Stat enum keys."""

    def __init__(self) -> None:
        self._counter: Counter[Stat] = Counter({stat: 0 for stat in Stat})

    def __getitem__(self, key: Stat) -> int:
        return self._counter[key]

    def __setitem__(self, key: Stat, value: int) -> None:
        self._counter[key] = value

    def __iadd__(self, other: Stats) -> Stats:
        """Support += operator for merging stats."""
        for stat in Stat:
            self._counter[stat] += other._counter[stat]
        return self


class SizeDiffAboveThreshold(Exception):
    """Difference in mail size is greater than `threshold
    <https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html#cmdoption-mdedup-S>`_.
    """


class ContentDiffAboveThreshold(Exception):
    """Difference in mail content is greater than `threshold
    <https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html#cmdoption-mdedup-C>`_.
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
        self, hash_key: str, mail_set: set[DedupMailMixin], conf: Config
    ) -> None:
        """Load-up the duplicate set of mail and freeze pool.

        Once loaded-up, the pool of parsed mails is considered frozen for the rest of
        the duplicate set's life. This allows aggressive caching of lazy instance
        attributes depending on the pool content.
        """
        self.hash_key: str = hash_key

        self.selection: set[Message] = set()
        """Mails selected after application of selection strategy."""

        self.discard: set[Message] = set()
        """Mails discarded after application of selection strategy."""

        self.conf = conf
        """Configuration shared from the main deduplication process."""

        self.pool: frozenset[DedupMailMixin] = frozenset(mail_set)
        """Pool referencing all duplicated mails and their attributes."""

        self.stats: Stats = Stats()
        """Set metrics."""

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
    def newest_timestamp(self):
        """Returns the newest timestamp among all mails in the set."""
        return max(map(attrgetter("timestamp"), self.pool))

    @cached_property
    def oldest_timestamp(self):
        """Returns the oldest timestamp among all mails in the set."""
        return min(map(attrgetter("timestamp"), self.pool))

    @cached_property
    def biggest_size(self):
        """Returns the biggest size among all mails in the set."""
        return max(map(attrgetter("size"), self.pool))

    @cached_property
    def smallest_size(self):
        """Returns the smallest size among all mails in the set."""
        return min(map(attrgetter("size"), self.pool))

    def check_differences(self):
        """Ensures all mail differs in the limits imposed by size and content
        thresholds.

        Compare all mails of the duplicate set with each other, both in size and
        content. Raise an error if we're not within the limits imposed by the threshold
        settings.
        """
        size_threshold = self.conf["size_threshold"]
        content_threshold = self.conf["content_threshold"]

        logging.info("Check mail differences are below the thresholds.")
        if size_threshold < 0:
            logging.info("Skip checking for size differences.")
        if content_threshold < 0:
            logging.info("Skip checking for content differences.")
        if size_threshold < 0 and content_threshold < 0:
            return

        for mail_a, mail_b in combinations(self.pool, 2):
            if size_threshold >= 0:
                size_difference = abs(mail_a.size - mail_b.size)
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {size_difference} bytes "
                    "in size.",
                )
                if size_difference > size_threshold:
                    raise SizeDiffAboveThreshold

            if content_threshold >= 0:
                content_difference = self.diff(mail_a, mail_b)
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {content_difference} bytes "
                    "in content.",
                )
                if content_difference > content_threshold:
                    if self.conf["show_diff"]:
                        logging.info(self.pretty_diff(mail_a, mail_b))
                    raise ContentDiffAboveThreshold

    def diff(self, mail_a, mail_b):
        """Return difference in bytes between two mails' normalized body.

        .. todo::
            Rewrite the diff algorithm to not rely on naive unified diff result parsing.
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
                fromfiledate=f"{mail_a.timestamp:0.2f}",
                tofiledate=f"{mail_b.timestamp:0.2f}",
                n=0,
                lineterm="\n",
            ),
        )

    def _skip_set(self, reason: str, stat: Stat) -> None:
        """Mark the entire set as skipped."""
        logging.warning(f"Skip set: {reason}")
        self.stats[Stat.MAIL_SKIPPED] += self.size
        self.stats[stat] += 1

    def categorize_candidates(self):
        """Process the list of duplicates for action.

        Run preliminary checks, then apply the strategy to the pool of mails.

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
            self.check_differences()
        except UnicodeDecodeError as expt:
            logging.debug(f"{expt}")
            return self._skip_set(
                "unparsable mails due to bad encoding.", Stat.SET_SKIPPED_ENCODING
            )
        except SizeDiffAboveThreshold:
            return self._skip_set(
                "mails are too dissimilar in size.", Stat.SET_SKIPPED_SIZE
            )
        except ContentDiffAboveThreshold:
            return self._skip_set(
                "mails are too dissimilar in content.", Stat.SET_SKIPPED_CONTENT
            )

        if not self.conf["strategy"]:
            return self._skip_set("no strategy to apply.", Stat.SET_SKIPPED_STRATEGY)

        # Fetch the subset of selected mails from the set by applying strategy.
        selected = self.conf["strategy"].apply_strategy(self)
        candidate_count = len(selected)

        # Duplicate sets matching as a whole are skipped altogether.
        if candidate_count == self.size:
            return self._skip_set(
                f"all {candidate_count} mails within were selected. "
                "The strategy criterion was not able to discard some.",
                Stat.SET_SKIPPED_STRATEGY,
            )

        # Duplicate sets matching none are skipped altogether.
        if candidate_count == 0:
            return self._skip_set(
                "No mail within were selected. "
                "The strategy criterion was not able to select some.",
                Stat.SET_SKIPPED_STRATEGY,
            )

        logging.info(f"{candidate_count} mail candidates selected for action.")
        self.stats[Stat.MAIL_SELECTED] += candidate_count
        self.stats[Stat.MAIL_DISCARDED] += self.size - candidate_count
        self.stats[Stat.SET_DEDUPLICATED] += 1
        self.selection = selected
        self.discard = self.pool.difference(selected)


class Deduplicate:
    """Load-up messages, search for duplicates, apply selection strategy and perform the
    action.

    Similar messages sharing the same hash are grouped together in a ``DuplicateSet``.
    """

    CLEANUP_ATTRS: tuple[str, ...] = ("canonical_headers", "body_lines", "subject")
    """Attributes to remove from mails after categorization to free memory."""

    def __init__(self, conf: Config) -> None:
        self.sources: dict[str, Mailbox] = {}
        """Index of mail sources by their full, normalized path. So we can refer
        to them in Mail instances. Also have the nice side effect of natural
        deduplication of sources themselves.
        """

        self.mails: dict[str, set[Message]] = {}
        """All mails grouped by hashes."""

        self.selection: set[Message] = set()
        """Mails selected after application of selection strategy."""

        self.discard: set[Message] = set()
        """Mails discarded after application of selection strategy."""

        self.conf = conf
        """Configuration shared across the deduplication process."""

        self.stats: Stats = Stats()
        """Deduplication statistics."""

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
        """
        logging.info(
            f"Use [{', '.join(map(theme.choice, self.conf['hash_headers']))}] headers to "
            "compute hashes.",
        )

        body_hasher = self.conf["hash_body"].hash_function()

        with progressbar(
            length=self.stats[Stat.MAIL_FOUND],
            label="Hashed mails",
            show_pos=True,
        ) as progress:
            for box in self.sources.values():
                for mail_id, mail in box.iteritems():
                    mail.add_box_metadata(box, mail_id)

                    mail.conf = self.conf

                    try:
                        mail_hash = mail.hash_key() + body_hasher(mail)
                    except TooFewHeaders as expt:
                        logging.warning(f"Rejecting {mail!r}: {expt.args[0]}")
                        self.stats[Stat.MAIL_REJECTED] += 1
                    else:
                        # Use a set to deduplicate entries pointing to the same file.
                        self.mails.setdefault(mail_hash, set()).add(mail)
                        self.stats[Stat.MAIL_RETAINED] += 1

                    progress.update(1)

        self.stats[Stat.MAIL_HASHES] += len(self.mails)

    @staticmethod
    def _cleanup_mail_attrs(mail: Message, attrs: list[str]) -> None:
        """Remove cached attributes from mail to free memory."""
        for name in attrs:
            mail.__dict__.pop(name, None)

    def build_sets(self):
        """Build the selected and discarded sets from each duplicate set.

        We apply the selection strategy one duplicate set at a time to keep memory
        footprint low and make the log easier to read.
        """
        if self.conf["strategy"]:
            logging.info(
                f"{theme.choice(self.conf['strategy'])} strategy will be applied on each "
                "duplicate set to select candidates.",
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

            # Remove from mail objects all attributes we no longer need.
            # See: https://github.com/kdeldycke/mail-deduplicate/issues/362
            for mail in duplicates.discard | duplicates.selection:
                self._cleanup_mail_attrs(mail, self.CLEANUP_ATTRS)
            if self.conf["action"] == "move-discarded":
                for mail in duplicates.selection:
                    mail.__dict__.pop("_payload", None)

    def close_all(self):
        """Close all open boxes."""
        for source_path, box in self.sources.items():
            logging.debug(f"Close {source_path}")
            box.close()

    def report(self):
        """Returns a text report of user-friendly statistics and metrics."""
        ctx = get_current_context()
        render_table = ctx.find_root().render_table

        output = ""
        for category, title in (("mail", "Mails"), ("set", "Duplicate sets")):
            table = [
                [
                    stat.name.removeprefix(f"{category.upper()}_")
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
            case "<=":
                passed = first_value <= second_value
            case "in":
                valid_values = (
                    [self.stats[s] for s in second]
                    if isinstance(second, tuple)
                    else [second_value]
                )
                passed = first_value in valid_values
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

        # Action stats.
        self.assert_stats(
            (Stat.MAIL_UNIQUE, Stat.MAIL_SELECTED), ">=", Stat.MAIL_COPIED
        )
        if self.conf["action"] != "move-discarded":
            # The number of moved mails may be larger than the number of selected
            # mails for move-discarded action, because discarded mails are moved.
            self.assert_stats(Stat.MAIL_SELECTED, ">=", Stat.MAIL_MOVED)
        self.assert_stats(
            (Stat.MAIL_UNIQUE, Stat.MAIL_SELECTED), ">=", Stat.MAIL_DELETED
        )
        self.assert_stats(
            (Stat.MAIL_UNIQUE, Stat.MAIL_SELECTED),
            "in",
            (Stat.MAIL_COPIED, Stat.MAIL_MOVED, Stat.MAIL_DELETED),
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
                Stat.SET_SKIPPED_STRATEGY,
                Stat.SET_DEDUPLICATED,
            ),
        )
