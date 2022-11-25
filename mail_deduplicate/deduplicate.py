# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
# All Rights Reserved.
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

import textwrap
from collections import Counter, OrderedDict
from difflib import unified_diff
from itertools import combinations
from operator import attrgetter
from pathlib import Path

import click
from boltons.cacheutils import cachedproperty
from boltons.dictutils import FrozenDict
from click_extra.colorize import default_theme as theme
from tabulate import tabulate

from . import ContentDiffAboveThreshold, SizeDiffAboveThreshold, TooFewHeaders, logger
from .mailbox import open_box
from .strategy import apply_strategy

STATS_DEF = OrderedDict(
    [
        ("mail_found", "Total number of mails encountered from all mail sources."),
        (
            "mail_rejected",
            "Number of mails rejected individually because they were unparseable or "
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
            "Number of mails ignored in the selection phase because the whole set "
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
    ]
)
"""All tracked statistics and their definition."""


BODY_HASHER_SKIP = "skip"
BODY_HASHER_RAW = "raw"
BODY_HASHER_NORMALIZED = "normalized"
BODY_HASHERS = FrozenDict(
    {
        BODY_HASHER_SKIP: lambda _: "",
        BODY_HASHER_RAW: lambda m: m.hash_raw_body,
        BODY_HASHER_NORMALIZED: lambda m: m.hash_normalized_body,
    }
)
"""Body hashers."""


class DuplicateSet:

    """A set of mails sharing the same hash.

    Implements all the safety checks required before we can apply any selection
    strategy.
    """

    def __init__(self, hash_key, mail_set, conf):
        """Load-up the duplicate set of mail and freeze pool.

        Once loaded-up, the pool of parsed mails is considered frozen for the rest of
        the duplicate set's life. This allows aggressive caching of lazy instance
        attributes depending on the pool content.
        """
        self.hash_key = hash_key

        # Mails selected after application of selection strategy.
        self.selection = set()

        # Mails discarded after application of selection strategy.
        self.discard = set()

        # Global config.
        self.conf = conf

        # Pool referencing all duplicated mails and their attributes.
        self.pool = frozenset(mail_set)

        # Set metrics.
        self.stats = Counter()
        self.stats["mail_duplicates"] += self.size

        logger.debug(f"{self!r} created.")

    def __repr__(self):
        """Print internal raw states for debugging."""
        return f"<{self.__class__.__name__} hash={self.hash_key} size={self.size}>"

    @cachedproperty
    def size(self):
        """Return the size of the duplicate set."""
        return len(self.pool)

    @cachedproperty
    def newest_timestamp(self):
        return max(map(attrgetter("timestamp"), self.pool))

    @cachedproperty
    def oldest_timestamp(self):
        return min(map(attrgetter("timestamp"), self.pool))

    @cachedproperty
    def biggest_size(self):
        return max(map(attrgetter("size"), self.pool))

    @cachedproperty
    def smallest_size(self):
        return min(map(attrgetter("size"), self.pool))

    def check_differences(self):
        """Ensures all mail differs in the limits imposed by size and content
        thresholds.

        Compare all mails of the duplicate set with each other, both in size and
        content. Raise an error if we're not within the limits imposed by the threshold
        settings.
        """
        logger.info("Check mail differences are below the thresholds.")
        if self.conf.size_threshold < 0:
            logger.info("Skip checking for size differences.")
        if self.conf.content_threshold < 0:
            logger.info("Skip checking for content differences.")
        if self.conf.size_threshold < 0 and self.conf.content_threshold < 0:
            return

        # Compute differences of mail against one another.
        for mail_a, mail_b in combinations(self.pool, 2):

            # Compare mails on size.
            if self.conf.size_threshold > -1:
                size_difference = abs(mail_a.size - mail_b.size)
                logger.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {size_difference} bytes "
                    "in size."
                )
                if size_difference > self.conf.size_threshold:
                    raise SizeDiffAboveThreshold

            # Compare mails on content.
            if self.conf.content_threshold > -1:
                content_difference = self.diff(mail_a, mail_b)
                logger.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {content_difference} bytes "
                    "in content."
                )
                if content_difference > self.conf.content_threshold:
                    if self.conf.show_diff:
                        logger.info(self.pretty_diff(mail_a, mail_b))
                    raise ContentDiffAboveThreshold

    def diff(self, mail_a, mail_b):
        """Return difference in bytes between two mails' normalized body.

        .. todo::     Rewrite the diff algorithm to not rely on naive unified diff
        result parsing.
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
                )
            )
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
            )
        )

    def categorize_candidates(self):
        """Process the list of duplicates for action.

        Run preliminary checks and fill the corresponding sets fitting the configured
        strategy and safety checks.
        """
        # Fine-grained checks on mail differences.
        try:
            self.check_differences()
        except UnicodeDecodeError as expt:
            logger.warning("Skip set: unparseable mails due to bad encoding.")
            logger.debug(f"{expt}")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_encoding"] += 1
            return
        except SizeDiffAboveThreshold:
            logger.warning("Skip set: mails are too dissimilar in size.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_size"] += 1
            return
        except ContentDiffAboveThreshold:
            logger.warning("Skip set: mails are too dissimilar in content.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_content"] += 1
            return

        if not self.conf.strategy:
            logger.warning("Skip set: no strategy to apply.")
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        # Fetch the subset of selected mails from the set by applying strategy.
        selected = apply_strategy(self.conf.strategy, self)
        candidate_count = len(selected)

        # Duplicate sets matching as a whole are skipped altogether.
        if candidate_count == self.size:
            logger.warning(
                f"Skip set: all {candidate_count} mails within were selected. "
                "The strategy criterion was not able to discard some."
            )
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        # Duplicate sets matching none are skipped altogether.
        if candidate_count == 0:
            logger.warning(
                f"Skip set: No mail within were selected. "
                "The strategy criterion was not able to select some."
            )
            self.stats["mail_skipped"] += self.size
            self.stats["set_skipped_strategy"] += 1
            return

        logger.info(f"{candidate_count} mail candidates selected for action.")
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

    def __init__(self, conf):
        # Index of mail sources by their full, normalized path. So we can refer
        # to them in Mail instances. Also have the nice side effect of natural
        # deduplication of sources themselves.
        self.sources = {}

        # All mails grouped by hashes.
        self.mails = {}

        # Mails selected after application of selection strategy.
        self.selection = set()

        # Mails discarded after application of selection strategy.
        self.discard = set()

        # Global config.
        self.conf = conf

        # Deduplication statistics.
        self.stats = Counter(dict.fromkeys(STATS_DEF, 0))

    def add_source(self, source_path):
        """Registers a source of mails, validates and opens it."""
        # Make the path absolute, resolving any symlinks. Do not allow duplicates in
        # our sources, as we use the path as a unique key to tie back a mail from its
        # source when performing the action later.
        source_path = str(Path(source_path).resolve(strict=True))
        if source_path in self.sources:
            raise ValueError(f"{source_path} already added.")

        # Open and register the mail source. Subfolders will be registered as their
        # own box.
        boxes = open_box(source_path, self.conf.input_format, self.conf.force_unlock)
        for box in boxes:
            self.sources[box._path] = box

            # Track global mail count.
            mail_found = len(box)
            logger.info(f"{mail_found} mails found.")
            self.stats["mail_found"] += mail_found

    def hash_all(self):
        """Browse all mails from all registered sources, compute hashes and group mails
        by hash.

        Displays a progress bar as the operation might be slow.
        """
        logger.info(
            f"Use [{', '.join(map(theme.choice, self.conf.hash_headers))}] headers to "
            "compute hashes."
        )

        body_hasher = BODY_HASHERS.get(self.conf.hash_body)
        if not body_hasher:
            raise NotImplementedError(
                f"{self.conf.hash_body} body hasher not implemented yet."
            )

        with click.progressbar(
            length=self.stats["mail_found"],
            label="Hashed mails",
            show_pos=True,
        ) as progress:

            for box in self.sources.values():
                for mail_id, mail in box.iteritems():

                    mail.add_box_metadata(box, mail_id)

                    mail.conf = self.conf

                    try:
                        mail_hash = mail.hash_key + body_hasher(mail)
                    except TooFewHeaders as expt:
                        logger.warning(f"Rejecting {mail!r}: {expt.args[0]}")
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
        if self.conf.strategy:
            logger.info(
                f"{theme.choice(self.conf.strategy)} strategy will be applied on each "
                "duplicate set to select candidates."
            )
        else:
            logger.warning("No strategy configured, skip selection.")

        self.stats["set_total"] = len(self.mails)

        for hash_key, mail_set in self.mails.items():

            # Alter log level depending on set length.
            mail_count = len(mail_set)
            log_level = logger.debug if mail_count == 1 else logger.info
            log_level(theme.subheading(f"◼ {mail_count} mails sharing hash {hash_key}"))

            # Apply the selection strategy to discriminate mails within the set.
            duplicates = DuplicateSet(hash_key, mail_set, self.conf)
            duplicates.categorize_candidates()
            # Merge duplicate set's stats to global stats.
            self.stats += duplicates.stats
            self.selection.update(duplicates.selection)
            self.discard.update(duplicates.discard)

    def close_all(self):
        """Close all open boxes."""
        for source_path, box in self.sources.items():
            logger.debug(f"Close {source_path}")
            box.close()

    def report(self):
        """Returns a text report of user-friendly statistics and metrics."""
        output = ""
        for prefix, title in (("mail_", "Mails"), ("set_", "Duplicate sets")):
            table = [[title, "Metric", "Description"]]
            for stat_id, desc in STATS_DEF.items():
                if stat_id.startswith(prefix):
                    table.append(
                        [
                            stat_id[len(prefix) :].replace("_", " - ").title(),
                            self.stats[stat_id],
                            "\n".join(textwrap.wrap(desc, 60)),
                        ]
                    )
            output += tabulate(table, tablefmt="fancy_grid", headers="firstrow")
            output += "\n"
        return output

    def check_stats(self):
        """Perform some high-level consistency checks on metrics.

        Helps users reports tricky edge-cases.
        """
        # Box opening stats.
        assert self.stats["mail_found"] >= self.stats["mail_rejected"]
        assert self.stats["mail_found"] >= self.stats["mail_retained"]
        assert self.stats["mail_found"] == (
            self.stats["mail_rejected"] + self.stats["mail_retained"]
        )
        # Mail grouping by hash.
        assert self.stats["mail_retained"] >= self.stats["mail_unique"]
        assert self.stats["mail_retained"] >= self.stats["mail_duplicates"]
        assert self.stats["mail_retained"] == (
            self.stats["mail_unique"] + self.stats["mail_duplicates"]
        )
        # Mail selection stats.
        assert self.stats["mail_retained"] >= self.stats["mail_skipped"]
        assert self.stats["mail_retained"] >= self.stats["mail_discarded"]
        assert self.stats["mail_retained"] >= self.stats["mail_selected"]
        assert self.stats["mail_retained"] == (
            self.stats["mail_skipped"]
            + self.stats["mail_discarded"]
            + self.stats["mail_selected"]
        )
        # Action stats.
        assert self.stats["mail_selected"] >= self.stats["mail_copied"]
        assert self.stats["mail_selected"] >= self.stats["mail_moved"]
        assert self.stats["mail_selected"] >= self.stats["mail_deleted"]
        assert self.stats["mail_selected"] in (
            self.stats["mail_copied"],
            self.stats["mail_moved"],
            self.stats["mail_deleted"],
        )
        # Sets accounting.
        assert self.stats["set_total"] == self.stats["mail_hashes"]
        assert self.stats["set_single"] == self.stats["mail_unique"]
        assert self.stats["set_total"] == (
            self.stats["set_single"]
            + self.stats["set_skipped_encoding"]
            + self.stats["set_skipped_size"]
            + self.stats["set_skipped_content"]
            + self.stats["set_skipped_strategy"]
            + self.stats["set_deduplicated"]
        )
