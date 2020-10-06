# -*- coding: utf-8 -*-
#
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

import re
from collections import Counter
from difflib import unified_diff
from itertools import combinations
from operator import attrgetter
from pathlib import Path

from boltons.cacheutils import cachedproperty
from boltons.iterutils import unique
from tabulate import tabulate
import click

from . import (
    ContentDiffAboveThreshold,
    TooFewHeaders,
    SizeDiffAboveThreshold,
    logger,
)
from .mailbox import open_box


DRY_RUN_LABEL = click.style("DRY_RUN", fg="yellow")


class DuplicateSet:

    """A duplicate set of mails sharing the same hash.

    Implements all deletion strategies applicable to a set of duplicate mails.
    """

    def __init__(self, hash_key, mail_set, conf):
        """Load-up the duplicate set of mail and freeze pool.

        Once loaded-up, the pool of parsed mails is considered frozen for the
        rest of the duplicate set life. This allow aggressive caching of lazy
        instance attributes depending on the pool content.
        """
        self.hash_key = hash_key

        # Global config.
        self.conf = conf

        # Pool referencing all duplicated mails and their attributes.
        self.pool = frozenset(mail_set)

        # Keep set metrics.
        self.stats = Counter()

        logger.debug(f"{self!r} created.")

    def __repr__(self):
        """ Print internal raw states for debugging. """
        return "<{} hash={}, size={}, conf={!r}, pool={!r}>".format(
            self.__class__.__name__, self.hash_key, self.size, self.conf, self.pool
        )

    @cachedproperty
    def size(self):
        """ Return the size of the duplicate set. """
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

        Compare all mails of the duplicate set with each other, both in size
        and content. Raise an error if we're not within the limits imposed by
        the threshold settings.
        """
        logger.info("Check that mail differences are within the limits.")
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
                    f"{mail_a!r} and {mail_b!r} differs by {size_difference} bytes in size."
                )
                if size_difference > self.conf.size_threshold:
                    raise SizeDiffAboveThreshold

            # Compare mails on content.
            if self.conf.content_threshold > -1:
                content_difference = self.diff(mail_a, mail_b)
                logger.debug(
                    f"{mail_a!r} and {mail_b!r} differs by {content_difference} bytes in "
                    "content."
                )
                if content_difference > self.conf.content_threshold:
                    if self.conf.show_diff:
                        logger.info(self.pretty_diff(mail_a, mail_b))
                    raise ContentDiffAboveThreshold

    def diff(self, mail_a, mail_b):
        """Return difference in bytes between two mails' normalized body.

        TODO: rewrite the diff algorithm to not rely on naive unified diff
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
                fromfile="Normalized body of {}".format(mail_a.path),
                tofile="Normalized body of {}".format(mail_b.path),
                fromfiledate="{:0.2f}".format(mail_a.timestamp),
                tofiledate="{:0.2f}".format(mail_b.timestamp),
                n=0,
                lineterm="\n",
            )
        )

    def call_strategy(self):
        """Call deduplication with the configured strategy.

        Transform strategy keyword into its method ID, and call it.
        """
        if not self.conf.strategy:
            logger.warning("No strategy selected, skip deduplication.")
            return

        method_id = self.conf.strategy.replace("-", "_")
        if not hasattr(DuplicateSet, method_id):
            raise NotImplementedError("DuplicateSet.{}() method.".format(method_id))
        logger.debug(f"Call {method_id}() strategy.")
        return getattr(self, method_id)()

    def select_candidates(self):
        """Returns the list of duplicates selected for removal.

        Run preliminary checks and return the candidates fitting the strategy
        and constraints set by the configuration."""
        if self.size == 1:
            logger.debug(
                "Ignore set: no need to deduplicate as only one message found."
            )
            self.stats["mail_unique"] += self.size
            self.stats["set_ignored"] += 1
            return

        self.stats["mail_duplicates"] += self.size

        # Fine-grained checks on mail differences.
        try:
            self.check_differences()
        except UnicodeDecodeError as expt:
            self.stats["set_rejected_encoding"] += 1
            logger.warning("Reject set: unparseable mails due to bad encoding.")
            logger.debug(f"{expt}")
            return
        except SizeDiffAboveThreshold:
            self.stats["set_rejected_size"] += 1
            logger.warning("Reject set: mails are too dissimilar in size.")
            return
        except ContentDiffAboveThreshold:
            self.stats["set_rejected_content"] += 1
            logger.warning("Reject set: mails are too dissimilar in content.")
            return

        # Apply the selection strategy to the set.
        selected_mails = self.call_strategy()

        # Count duplicate sets matching as a whole as skipped: no deletion will
        # happens.
        candidate_count = len(selected_mails)
        if candidate_count == self.size:
            logger.warning(
                f"Skip deletion: all {candidate_count} mails of the set match the "
                "strategy criterion."
            )
            self.stats["set_skipped"] += 1
            return

        logger.info(f"{candidate_count} candidates found for deletion.")
        self.stats["set_deduplicated"] += 1
        return [(mail.source_path, mail.mail_id) for mail in selected_mails]

    # TODO: Factorize reduce the code structure common to all strategy below
    # around the notion of selection criterion.

    def delete_older(self):
        """Delete all older duplicates.

        Only keeps the subset sharing the most recent timestamp.
        """
        logger.info(
            f"Select all mails strictly older than the {self.newest_timestamp} "
            "timestamp..."
        )
        return [mail for mail in self.pool if mail.timestamp < self.newest_timestamp]

    def delete_oldest(self):
        """Delete all the oldest duplicates.

        Keeps all mail of the duplicate set but those sharing the oldest
        timestamp.
        """
        logger.info(
            f"Select all mails sharing the oldest {self.oldest_timestamp} "
            "timestamp..."
        )
        return [mail for mail in self.pool if mail.timestamp == self.oldest_timestamp]

    def delete_newer(self):
        """Delete all newer duplicates.

        Only keeps the subset sharing the most ancient timestamp.
        """
        logger.info(
            f"Select all mails strictly newer than the {self.oldest_timestamp} "
            "timestamp..."
        )
        return [mail for mail in self.pool if mail.timestamp > self.oldest_timestamp]

    def delete_newest(self):
        """Delete all the newest duplicates.

        Keeps all mail of the duplicate set but those sharing the newest
        timestamp.
        """
        logger.info(
            f"Select all mails sharing the newest {self.newest_timestamp} "
            "timestamp..."
        )
        return [mail for mail in self.pool if mail.timestamp == self.newest_timestamp]

    def delete_smaller(self):
        """Delete all smaller duplicates.

        Only keeps the subset sharing the biggest size.
        """
        logger.info(
            f"Select all mails strictly smaller than {self.biggest_size} bytes..."
        )
        return [mail for mail in self.pool if mail.size < self.biggest_size]

    def delete_smallest(self):
        """Delete all the smallest duplicates.

        Keeps all mail of the duplicate set but those sharing the smallest
        size.
        """
        logger.info(
            f"Select all mails sharing the smallest size of {self.smallest_size} "
            "bytes..."
        )
        return [mail for mail in self.pool if mail.size == self.smallest_size]

    def delete_bigger(self):
        """Delete all bigger duplicates.

        Only keeps the subset sharing the smallest size.
        """
        logger.info(
            f"Select all mails strictly bigger than {self.smallest_size} bytes..."
        )
        return [mail for mail in self.pool if mail.size > self.smallest_size]

    def delete_biggest(self):
        """Delete all the biggest duplicates.

        Keeps all mail of the duplicate set but those sharing the biggest
        size.
        """
        logger.info(
            f"Select all mails sharing the biggest size of {self.biggest_size} "
            "bytes..."
        )
        return [mail for mail in self.pool if mail.size == self.biggest_size]

    def delete_matching_path(self):
        """ Delete all duplicates whose file path match the regexp. """
        logger.info(
            f"Select all mails with file path matching the "
            "{self.conf.regexp.pattern} regexp..."
        )
        # Select candidates for deletion.
        return [mail for mail in self.pool if re.search(self.conf.regexp, mail.path)]

    def delete_non_matching_path(self):
        """ Delete all duplicates whose file path doesn't match the regexp. """
        logger.info(
            f"Select all mails with file path not matching the "
            "{self.conf.regexp.pattern} regexp..."
        )
        return [
            mail for mail in self.pool if not re.search(self.conf.regexp, mail.path)
        ]


class Deduplicate:

    """Load-up messages, search for duplicates and delete them.

    Similar messages sharing the same hash are grouped together in a ``DuplicateSet``.
    """

    def __init__(self, conf):
        # Index of mail sources by their full, normalized path. So we can refer
        # to them in Mail instances. Also have the nice side effect of natural
        # deduplication of sources themselves.
        self.sources = {}

        # All mails grouped by hashes.
        self.mails = {}

        # List of candidates selected for deletion.
        self.candidates = []

        # Global config.
        self.conf = conf

        # Deduplication statistics.
        self.stats = Counter(
            {
                # Total number of mails encountered in all mail sources.
                "mail_found": 0,
                # Number of mails ignored because they were faulty or unparseable.
                "mail_rejected": 0,
                # Number of valid mails parsed and retained for deduplication.
                "mail_kept": 0,
                # Number of unique mails (which ended up in duplicate sets with
                # one mail and one only).
                "mail_unique": 0,
                # Number of duplicate mails (sum of mails in all duplicate sets
                # with at least 2 mails).
                "mail_duplicates": 0,
                # Number of mails removed.
                "mail_deleted": 0,
                # Total number of duplicate sets.
                "set_total": 0,
                # Total number of unprocessed sets because mail is unique.
                "set_ignored": 0,
                # Total number of sets skipped as already deduplicated.
                "set_skipped": 0,
                # Number of sets ignored because they were faulty.
                "set_rejected_encoding": 0,
                "set_rejected_size": 0,
                "set_rejected_content": 0,
                # Number of valid sets successfuly deduplicated.
                "set_deduplicated": 0,
            }
        )

    def add_source(self, source_path):
        """Registers a source of mails, validates and opens it. """
        # Make the path absolute, resolving any symlinks. Do not allow duplicates in
        # our sources, as we use the path as a unique key to tie back a mail
        # from its source on deletion later.
        source_path = Path(source_path).resolve(strict=True)
        if source_path in self.sources:
            raise ValueError(f"{source_path} already added.")

        # Open and register the mail source.
        box = open_box(source_path, self.conf.sources_format, self.conf.force_unlock)
        self.sources[source_path] = box

        # Keep track of global mail count.
        mail_found = len(box)
        logger.info(f"{mail_found} mails found.")
        self.stats["mail_found"] += mail_found

    def hash_all(self):
        """Browse all mails from all registered sources, compute hashes and
        group mails by hash.

        Displays a progress bar as the operation might be slow.
        """
        logger.info(
            "Use [{}] headers to compute hashes.".format(
                ", ".join(
                    [click.style(h, fg="bright_white") for h in self.conf.hash_headers]
                )
            )
        )

        with click.progressbar(
            length=self.stats["mail_found"],
            label="Mails hashed",
            show_pos=True,
        ) as progress:

            for source_path, box in self.sources.items():
                for mail_id, mail in box.iteritems():

                    # Re-attach box_path and mail_id to let the mail carry its
                    # own information on its origin box and index in this box.
                    mail.mail_id = mail_id
                    mail.source_path = source_path
                    mail.conf = self.conf

                    try:
                        mail_hash = mail.hash_key
                    except TooFewHeaders as expt:
                        logger.warning(f"Rejecting {mail.path}: {expt.args[0]}")
                        self.stats["mail_rejected"] += 1
                    else:
                        # Use a set to deduplicate entries pointing to the same file.
                        self.mails.setdefault(mail_hash, set()).add(mail)
                        self.stats["mail_kept"] += 1

                    progress.update(1)

    def gather_candidates(self):
        """Gather all candidates for deletion from each duplicate set.

        We apply the removal strategy one duplicate set at a time to keep
        memory footprint low and make the log of actions easier to read.
        """
        if self.conf.strategy:
            logger.info(
                f"{self.conf.strategy} strategy will be applied on each "
                "duplicate set to select candidates."
            )
        else:
            logger.warning("No removal strategy will be applied.")

        self.stats["set_total"] = len(self.mails)

        for hash_key, mail_set in self.mails.items():

            # Alter log level depending on set length.
            mail_count = len(mail_set)
            log_level = logger.debug if mail_count == 1 else logger.info
            log_level(
                click.style(f"◼ {mail_count} mails sharing hash {hash_key}", fg="cyan")
            )

            # Performs the deduplication within the set.
            duplicates = DuplicateSet(hash_key, mail_set, self.conf)
            candidates = duplicates.select_candidates()
            if candidates:
                self.candidates += candidates

            # Merge stats resulting of actions on duplicate sets.
            self.stats += duplicates.stats

        # Close all open boxes.
        for box in self.sources.values():
            box.close()

    def remove_duplicates(self):
        """Performs the action of removing the selected mail candidates
        in-place, from their original boxes."""
        # Check our indexing and selection methods are not flagging candidates
        # several times.
        assert unique(self.candidates) == self.candidates

        for box_path, mail_id in self.candidates:
            # TODO: fetch mail path from Mail object instance directly.
            mail_path = "{}:{}".format(box_path, mail_id)
            self.stats["mail_deleted"] += 1

            if self.conf.dry_run:
                logger.warning(f"{DRY_RUN_LABEL}: skip deletion of {mail_path!r}.")
                return

            logger.debug(f"Deleting {mail_path!r}...")
            self.sources[box_path].remove(mail_id)
            logger.info(f"{mail_path} deleted.")

    def report(self):
        """ Returns a text report of user-friendly statistics and metrics. """
        table = [
            ["Mails", "Metric"],
            ["Found", self.stats["mail_found"]],
            ["Rejected", self.stats["mail_rejected"]],
            ["Kept", self.stats["mail_kept"]],
            ["Unique", self.stats["mail_unique"]],
            ["Duplicates", self.stats["mail_duplicates"]],
            ["Deleted", self.stats["mail_deleted"]],
        ]
        output = tabulate(table, tablefmt="fancy_grid", headers="firstrow")

        table = [
            ["Duplicate sets", "Metric"],
            ["Total", self.stats["set_total"]],
            ["Ignored", self.stats["set_ignored"]],
            ["Skipped", self.stats["set_skipped"]],
            ["Rejected (bad encoding)", self.stats["set_rejected_encoding"]],
            ["Rejected (too dissimilar in size)", self.stats["set_rejected_size"]],
            [
                "Rejected (too dissimilar in content)",
                self.stats["set_rejected_content"],
            ],
            ["Deduplicated", self.stats["set_deduplicated"]],
        ]
        output += "\n"
        output += tabulate(table, tablefmt="fancy_grid", headers="firstrow")

        return output

    def check_stats(self):
        """Perform some high-level consistency checks on metrics.

        Helps users reports tricky edge-cases.
        """
        assert self.stats["mail_found"] >= self.stats["mail_rejected"]
        assert self.stats["mail_found"] >= self.stats["mail_kept"]
        assert self.stats["mail_found"] == (
            self.stats["mail_rejected"] + self.stats["mail_kept"]
        )

        assert self.stats["mail_kept"] >= self.stats["mail_unique"]
        assert self.stats["mail_kept"] >= self.stats["mail_duplicates"]
        assert self.stats["mail_kept"] == (
            self.stats["mail_unique"] + self.stats["mail_duplicates"]
        )

        assert self.stats["mail_kept"] >= self.stats["mail_deleted"]
        assert self.stats["mail_duplicates"] == 0 or (
            self.stats["mail_duplicates"] > self.stats["mail_deleted"]
        )

        assert self.stats["set_ignored"] == self.stats["mail_unique"]

        assert self.stats["set_total"] == (
            self.stats["set_ignored"]
            + self.stats["set_rejected_encoding"]
            + self.stats["set_rejected_size"]
            + self.stats["set_rejected_content"]
            + self.stats["set_skipped"]
            + self.stats["set_deduplicated"]
        )
