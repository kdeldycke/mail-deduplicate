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
from collections import Counter, OrderedDict
from difflib import unified_diff
from enum import Enum
from functools import cached_property
from itertools import combinations
from operator import attrgetter
from pathlib import Path

from click_extra import get_current_context, progressbar
from click_extra.colorize import default_theme as theme

from .mail import TooFewHeaders
from .mail_box import open_box

TYPE_CHECKING = False
if TYPE_CHECKING:
    from mailbox import Mailbox, Message

    from .cli import Config
    from .mail import DedupMailMixin


STATS_DEF = OrderedDict(
    [
        ("mail_found", "Total number of mails encountered from all mail sources."),
        (
            "mail_rejected",
            "Number of mails rejected individually because they were unparsable or "
            "did not have enough metadata to compute hashes.",
        ),
        (
            "mail_retained",
            "Number of valid mails parsed and retained for deduplication.",
        ),
        ("mail_hashes", "Number of unique hashes."),
        (
            "mail_unique",
            "Number of unique mails (which where automatically added to selection).",
        ),
        (
            "mail_duplicates",
            "Number of duplicate mails (sum of mails in all duplicate sets with at "
            "least 2 mails).",
        ),
        (
            "mail_skipped",
            "Number of mails ignored in the selection step because the whole set "
            "they belong to was skipped.",
        ),
        ("mail_discarded", "Number of mails discarded from the final selection."),
        (
            "mail_selected",
            "Number of mails kept in the final selection on which the "
            "action will be performed.",
        ),
        (
            "mail_copied",
            "Number of mails copied from their original mailbox to another.",
        ),
        ("mail_moved", "Number of mails moved from their original mailbox to another."),
        ("mail_deleted", "Number of mails deleted from their mailbox in-place."),
        ("set_total", "Total number of duplicate sets."),
        (
            "set_single",
            "Total number of sets containing only a single mail with no applicable "
            "strategy. They were automatically kept in the final selection.",
        ),
        (
            "set_skipped_encoding",
            "Number of sets skipped from the selection process because they had "
            "encoding issues.",
        ),
        (
            "set_skipped_size",
            "Number of sets skipped from the selection process because they were "
            "too dissimilar in size.",
        ),
        (
            "set_skipped_content",
            "Number of sets skipped from the selection process because they were "
            "too dissimilar in content.",
        ),
        (
            "set_skipped_strategy",
            "Number of sets skipped from the selection process because the strategy "
            "could not be applied.",
        ),
        (
            "set_deduplicated",
            "Number of valid sets on which the selection strategy was successfully "
            "applied.",
        ),
    ],
)
"""All tracked statistics and their definition."""


class SizeDiffAboveThreshold(Exception):
    """Difference in mail size is greater than `threshold
    <https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html#cmdoption-mdedup-S>`_.
    """


class ContentDiffAboveThreshold(Exception):
    """Difference in mail content is greater than `threshold
    <https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html#cmdoption-mdedup-C>`_.
    """


class BodyHasher(Enum):
    """Enumeration of available body hashing methods."""

    SKIP = "skip"
    RAW = "raw"
    NORMALIZED = "normalized"

    def __str__(self) -> str:
        return self.value  # type: ignore[no-any-return]

    def hash_function(self):
        """Returns the hashing function corresponding to the body hasher."""
        if self == BodyHasher.SKIP:
            return lambda _: ""
        elif self == BodyHasher.RAW:
            return lambda m: m.hash_raw_body
        elif self == BodyHasher.NORMALIZED:
            return lambda m: m.hash_normalized_body


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

        self.stats: Counter = Counter()
        """Set metrics."""

        self.stats["mail_duplicates"] += self.size

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
        logging.info("Check mail differences are below the thresholds.")
        if self.conf["size_threshold"] < 0:
            logging.info("Skip checking for size differences.")
        if self.conf["content_threshold"] < 0:
            logging.info("Skip checking for content differences.")
        if self.conf["size_threshold"] < 0 and self.conf["content_threshold"] < 0:
            return

        # Compute differences of mail against one another.
        for mail_a, mail_b in combinations(self.pool, 2):
            # Compare mails on size.
            if self.conf["size_threshold"] > -1:
                size_difference = abs(mail_a.size - mail_b.size)
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {size_difference} bytes "
                    "in size.",
                )
                if size_difference > self.conf["size_threshold"]:
                    raise SizeDiffAboveThreshold

            # Compare mails on content.
            if self.conf["content_threshold"] > -1:
                content_difference = self.diff(mail_a, mail_b)
                logging.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {content_difference} bytes "
                    "in content.",
                )
                if content_difference > self.conf["content_threshold"]:
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

    def categorize_candidates(self):
        """Process the list of duplicates for action.

        Run preliminary checks, then apply the strategy to the pool of mails.

        The process results in two subsets of mails: the selected and the discarded.
        """
        # Fine-grained checks on mail differences.

        if self.size == 1:
            self.stats["set_single"] += 1
            self.stats["mail_unique"] += 1
            self.stats["mail_duplicates"] = 0
            self.selection = set(self.pool)
            return

        try:
            self.check_differences()
        except UnicodeDecodeError as expt:
            logging.warning("Skip set: unparsable mails due to bad encoding.")
            logging.debug(f"{expt}")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_encoding"] += 1
            return
        except SizeDiffAboveThreshold:
            logging.warning("Skip set: mails are too dissimilar in size.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_size"] += 1
            return
        except ContentDiffAboveThreshold:
            logging.warning("Skip set: mails are too dissimilar in content.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_content"] += 1
            return

        if not self.conf["strategy"]:
            logging.warning("Skip set: no strategy to apply.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        # Fetch the subset of selected mails from the set by applying strategy.
        selected = self.conf["strategy"].apply_strategy(self)
        candidate_count = len(selected)

        # Duplicate sets matching as a whole are skipped altogether.
        if candidate_count == self.size:
            logging.warning(
                f"Skip set: all {candidate_count} mails within were selected. "
                "The strategy criterion was not able to discard some.",
            )
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        # Duplicate sets matching none are skipped altogether.
        if candidate_count == 0:
            logging.warning(
                "Skip set: No mail within were selected. "
                "The strategy criterion was not able to select some.",
            )
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        logging.info(f"{candidate_count} mail candidates selected for action.")
        self.stats["mail_selected"] += candidate_count
        self.stats["mail_discarded"] += self.size - candidate_count
        self.stats["set_deduplicated"] += 1
        self.selection = selected
        self.discard = self.pool.difference(selected)


class Deduplicate:
    """Load-up messages, search for duplicates, apply selection strategy and perform the
    action.

    Similar messages sharing the same hash are grouped together in a ``DuplicateSet``.
    """

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

        self.stats: Counter = Counter(dict.fromkeys(STATS_DEF, 0))
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
            self.stats["mail_found"] += mail_found

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
            length=self.stats["mail_found"],
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
                        self.stats["mail_rejected"] += 1
                    else:
                        # Use a set to deduplicate entries pointing to the same file.
                        self.mails.setdefault(mail_hash, set()).add(mail)
                        self.stats["mail_retained"] += 1

                    progress.update(1)

        self.stats["mail_hashes"] += len(self.mails)

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

        self.stats["set_total"] = len(self.mails)

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

            # Remove from mail objects all attributes we no longer need, now that we
            # have built the sets of selected and discarded mails. This will save
            # memory and speed-up the action.
            # See: https://github.com/kdeldycke/mail-deduplicate/issues/362
            delete_names = ["canonical_headers", "body_lines", "subject"]
            for mail in duplicates.discard:
                for name in delete_names:
                    if name in mail.__dict__:
                        del mail.__dict__[name]
            for mail in duplicates.selection:
                for name in delete_names:
                    if name in mail.__dict__:
                        del mail.__dict__[name]
                if self.conf["action"] == "move-discarded":
                    # Selection mails are not moved, delete payload.
                    del mail.__dict__["_payload"]

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
        for prefix, title in (("mail_", "Mails"), ("set_", "Duplicate sets")):
            table = []
            for stat_id, desc in STATS_DEF.items():
                if stat_id.startswith(prefix):
                    table.append(
                        [
                            stat_id[len(prefix) :].replace("_", " - ").title(),
                            self.stats[stat_id],
                            "\n".join(textwrap.wrap(desc, 60)),
                        ],
                    )
            output += render_table(table, headers=(title, "Metric", "Description"))
            output += "\n"
        return output

    def assert_stats(self, first, operator, second):
        """Render failed stats assertions in plain English.

        .. hint::
            If inconsistent metrics are detected, the CLI will exit with a code
            numbered ``115``.

            This has been arbitrarily chosen in `PR #842
            <https://github.com/kdeldycke/mail-deduplicate/pull/842#issuecomment-2815533315>`_,
            to make it unlikely to conflict with other exit codes. Users can rely on
            ``115`` meaning that the statistics checks failed.
        """
        if (
            (operator == ">=" and self.stats[first] >= self.stats[second])
            or (operator == "==" and self.stats[first] == self.stats[second])
            or (operator == "<=" and self.stats[first] <= self.stats[second])
        ):
            return
        if operator == "in":
            values = [self.stats.get(stat, 0) for stat in second]
            if self.stats[first] in values:
                return
            logging.warning(
                "Metrics appear inconsistent.\n"
                + f"EXPECTED: {first} to be one of {second}\n"
                + f"          {self.stats[first]} to be one of {values}\n"
            )
            sys.exit(115)
        logging.warning(
            "Metrics appear inconsistent.\n"
            + f"EXPECTED: {first} {operator} {second}\n"
            + f"          {self.stats[first]} {operator} {self.stats[second]}\n"
        )
        sys.exit(115)

    def check_stats(self):
        """Perform some high-level consistency checks on metrics.

        Helps users reports tricky edge-cases.
        """
        # Box opening stats.
        self.assert_stats("mail_found", ">=", "mail_rejected")
        self.assert_stats("mail_found", ">=", "mail_retained")

        self.stats["mail_rejected + mail_retained"] = (
            self.stats["mail_rejected"] + self.stats["mail_retained"]
        )
        self.assert_stats("mail_found", "==", "mail_rejected + mail_retained")

        # Mail grouping by hash.
        self.assert_stats("mail_retained", ">=", "mail_unique")
        self.assert_stats("mail_retained", ">=", "mail_duplicates")
        self.stats["mail_unique + mail_duplicates"] = (
            self.stats["mail_unique"] + self.stats["mail_duplicates"]
        )
        self.assert_stats("mail_retained", "==", "mail_unique + mail_duplicates")

        # Mail selection stats.
        self.assert_stats("mail_retained", ">=", "mail_skipped")
        self.assert_stats("mail_retained", ">=", "mail_discarded")
        self.assert_stats("mail_retained", ">=", "mail_selected")

        self.stats["mail_unique + mail_skipped + mail_discarded + mail_selected"] = (
            self.stats["mail_unique"]
            + self.stats["mail_skipped"]
            + self.stats["mail_discarded"]
            + self.stats["mail_selected"]
        )
        self.assert_stats(
            "mail_retained",
            "==",
            "mail_unique + mail_skipped + mail_discarded + mail_selected",
        )

        # Action stats.
        self.stats["mail_unique + mail_selected"] = (
            self.stats["mail_unique"] + self.stats["mail_selected"]
        )
        self.assert_stats("mail_unique + mail_selected", ">=", "mail_copied")
        if self.conf["action"] != "move-discarded":
            # The number of moved mails may be larger than the number of selected
            # mails for move-discarded action, because discarded mails are moved.
            self.assert_stats("mail_selected", ">=", "mail_moved")
        self.assert_stats("mail_unique + mail_selected", ">=", "mail_deleted")
        self.assert_stats(
            "mail_unique + mail_selected",
            "in",
            ["mail_copied", "mail_moved", "mail_deleted"],
        )
        # Sets accounting.
        self.assert_stats("set_total", "==", "mail_hashes")
        self.assert_stats("set_single", "==", "mail_unique")
        self.stats[
            "set_single + set_skipped_encoding + set_skipped_size "
            + "+ set_skipped_content + set_skipped_strategy + set_deduplicated"
        ] = (
            self.stats["set_single"]
            + self.stats["set_skipped_encoding"]
            + self.stats["set_skipped_size"]
            + self.stats["set_skipped_content"]
            + self.stats["set_skipped_strategy"]
            + self.stats["set_deduplicated"]
        )
        self.assert_stats(
            "set_total",
            "==",
            "set_single + set_skipped_encoding + set_skipped_size + "
            "set_skipped_content + set_skipped_strategy + set_deduplicated",
        )
