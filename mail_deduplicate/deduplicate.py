# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2017 Kevin Deldycke <kevin@deldycke.com>
#                         and contributors.
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

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals
)

import os
import re
from collections import Counter
from difflib import unified_diff
from itertools import combinations
from mailbox import Maildir, mbox
from operator import attrgetter

from boltons.cacheutils import cachedproperty
from progressbar import Bar, Percentage, ProgressBar
from tabulate import tabulate

from . import (
    ContentDiffAboveThreshold,
    InsufficientHeadersError,
    MissingMessageID,
    SizeDiffAboveThreshold,
    logger
)
from .mail import Mail


class DuplicateSet(object):

    """ A duplicate set of mails sharing the same hash.

    Implements all deletion strategies applicable to a set of duplicate mails.
    """

    def __init__(self, hash_key, mail_set, conf):
        """ Load-up the duplicate set of mail and freeze pool.

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

        logger.debug("{!r} created.".format(self))

    def __repr__(self):
        """ Print internal raw states for debugging. """
        return "<{} hash={}, size={}, conf={!r}, pool={!r}>".format(
            self.__class__.__name__,
            self.hash_key, self.size, self.conf, self.pool)

    @cachedproperty
    def size(self):
        """ Return the size of the duplicate set. """
        return len(self.pool)

    @cachedproperty
    def newest_timestamp(self):
        return max(map(attrgetter('timestamp'), self.pool))

    @cachedproperty
    def oldest_timestamp(self):
        return min(map(attrgetter('timestamp'), self.pool))

    @cachedproperty
    def biggest_size(self):
        return max(map(attrgetter('size'), self.pool))

    @cachedproperty
    def smallest_size(self):
        return min(map(attrgetter('size'), self.pool))

    def delete(self, mail):
        """ Delete a mail from the filesystem. """
        self.stats['mail_deleted'] += 1
        if self.conf.dry_run:
            logger.info("Skip deletion of {!r}.".format(mail))
            return
        mail.delete()

    def check_differences(self):
        """ In-depth check of mail differences.

        Compare all mails of the duplicate set with each other, both in size
        and content. Raise an error if we're not within the limits imposed by
        the threshold setting.
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
                logger.debug("{} and {} differs by {} bytes in size.".format(
                    mail_a, mail_b, size_difference))
                if size_difference > self.conf.size_threshold:
                    raise SizeDiffAboveThreshold

            # Compare mails on content.
            if self.conf.content_threshold > -1:
                content_difference = self.diff(mail_a, mail_b)
                logger.debug(
                    "{} and {} differs by {} bytes in content.".format(
                        mail_a, mail_b, content_difference))
                if content_difference > self.conf.content_threshold:
                    if self.conf.show_diff:
                        logger.info(self.pretty_diff(mail_a, mail_b))
                    raise ContentDiffAboveThreshold

    def diff(self, mail_a, mail_b):
        """ Return difference in bytes between two mails' normalized body.

        TODO: rewrite the diff algorithm to not rely on naive unified diff
        result parsing.
        """
        return len(''.join(unified_diff(
            mail_a.body_lines, mail_b.body_lines,
            # Ignore difference in filename lenghts and timestamps.
            fromfile='a', tofile='b',
            fromfiledate='', tofiledate='',
            n=0, lineterm='\n')))

    def pretty_diff(self, mail_a, mail_b):
        """ Returns a verbose unified diff between two mails' normalized body.
        """
        return ''.join(unified_diff(
            mail_a.body_lines, mail_b.body_lines,
            fromfile='Normalized body of {}'.format(mail_a.path),
            tofile='Normalized body of {}'.format(mail_b.path),
            fromfiledate='{:0.2f}'.format(mail_a.timestamp),
            tofiledate='{:0.2f}'.format(mail_b.timestamp),
            n=0, lineterm='\n'))

    def apply_strategy(self):
        """ Apply deduplication with the configured strategy.

        Transform strategy keyword into its method ID, and call it.
        """
        if not self.conf.strategy:
            logger.warning("No strategy selected, skip deduplication.")

        method_id = self.conf.strategy.replace('-', '_')
        if not hasattr(DuplicateSet, method_id):
            raise NotImplementedError(
                "DuplicateSet.{}() method.".format(method_id))
        getattr(self, method_id)()

    def dedupe(self):
        """ Performs the deduplication and its preliminary checks. """
        if len(self.pool) == 1:
            logger.debug("Ignore set: only one message found.")
            self.stats['mail_unique'] += 1
            self.stats['set_ignored'] += 1
            return

        self.stats['mail_duplicates'] += self.size
        try:
            # Fine-grained checks on mail differences.
            self.check_differences()
            # Call the deduplication strategy.
            self.apply_strategy()
        except UnicodeDecodeError as expt:
            self.stats['set_rejected_encoding'] += 1
            logger.warning(
                "Reject set: unparseable mails due to bad encoding.")
            logger.debug(str(expt))
        except SizeDiffAboveThreshold:
            self.stats['set_rejected_size'] += 1
            logger.warning("Reject set: mails are too dissimilar in size.")
        except ContentDiffAboveThreshold:
            self.stats['set_rejected_content'] += 1
            logger.warning("Reject set: mails are too dissimilar in content.")
        else:
            # Count duplicate sets without deletion as skipped.
            if not self.stats['mail_deleted']:
                logger.info("Skip set: no deletion happened.")
                self.stats['set_skipped'] += 1
            else:
                self.stats['set_deduplicated'] += 1

    # TODO: Factorize code structure common to all strategy.

    def delete_older(self):
        """ Delete all older duplicates.

        Only keeps the subset sharing the most recent timestamp.
        """
        logger.info(
            "Deleting all mails strictly older than the {} timestamp..."
            "".format(self.newest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.timestamp < self.newest_timestamp]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same timestamp."
                "".format(self.size))
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_oldest(self):
        """ Delete all the oldest duplicates.

        Keeps all mail of the duplicate set but those sharing the oldest
        timestamp.
        """
        logger.info(
            "Deleting all mails sharing the oldest {} timestamp...".format(
                self.oldest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.timestamp == self.oldest_timestamp]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same timestamp."
                "".format(self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_newer(self):
        """ Delete all newer duplicates.

        Only keeps the subset sharing the most ancient timestamp.
        """
        logger.info(
            "Deleting all mails strictly newer than the {} timestamp..."
            "".format(self.oldest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.timestamp > self.oldest_timestamp]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same timestamp."
                "".format(self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_newest(self):
        """ Delete all the newest duplicates.

        Keeps all mail of the duplicate set but those sharing the newest
        timestamp.
        """
        logger.info(
            "Deleting all mails sharing the newest {} timestamp...".format(
                self.newest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.timestamp == self.newest_timestamp]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same timestamp."
                "".format(self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_smaller(self):
        """ Delete all smaller duplicates.

        Only keeps the subset sharing the biggest size.
        """
        logger.info(
            "Deleting all mails strictly smaller than {} bytes...".format(
                self.biggest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.size < self.biggest_size]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same size."
                "".format(self.size))
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_smallest(self):
        """ Delete all the smallest duplicates.

        Keeps all mail of the duplicate set but those sharing the smallest
        size.
        """
        logger.info(
            "Deleting all mails sharing the smallest size of {} bytes..."
            "".format(self.smallest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.size == self.smallest_size]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same size."
                "".format(self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_bigger(self):
        """ Delete all bigger duplicates.

        Only keeps the subset sharing the smallest size.
        """
        logger.info(
            "Deleting all mails strictly bigger than {} bytes...".format(
                self.smallest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.size > self.smallest_size]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same size."
                "".format(self.size))
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_biggest(self):
        """ Delete all the biggest duplicates.

        Keeps all mail of the duplicate set but those sharing the biggest
        size.
        """
        logger.info(
            "Deleting all mails sharing the biggest size of {} bytes..."
            "".format(self.biggest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if mail.size == self.biggest_size]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails share the same size."
                "".format(self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_matching_path(self):
        """ Delete all duplicates whose file path match the regexp. """
        logger.info(
            "Deleting all mails with file path matching the {} regexp..."
            "".format(self.conf.regexp.pattern))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if re.search(self.conf.regexp, mail.path)]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails matches the rexexp.".format(
                    self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)

    def delete_non_matching_path(self):
        """ Delete all duplicates whose file path doesn't match the regexp. """
        logger.info(
            "Deleting all mails with file path not matching the {} regexp..."
            "".format(self.conf.regexp.pattern))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if not re.search(self.conf.regexp, mail.path)]
        if len(candidates) == self.size:
            logger.warning(
                "Skip deletion: all {} mails matches the rexexp.".format(
                    self.size))
            return
        logger.info(
            "{} candidates found for deletion.".format(len(candidates)))
        for mail in candidates:
            self.delete(mail)


class Deduplicate(object):

    """ Read messages from maildirs and perform a deduplication.

    Messages are grouped together in a DuplicateSet
    """

    # Index of mail sources by their full, normalized path. So we can refer
    # to them in Mail instances. Also have the nice side effect of natural
    # deduplication of sources themselves.
    # TODO: Lock, unlock, flush and close mboxes and maildirs. See:
    # https://docs.python.org/2/library/mailbox.html#mailbox.Mailbox.flush
    sources = {}

    def __init__(self, conf):
        # All mails grouped by hashes.
        self.mails = {}

        # Global config.
        self.conf = conf

        # Deduplication statistics.
        self.stats = Counter({
            # Total number of mails encountered in all maildirs.
            'mail_found': 0,
            # Number of mails skipped because of user options.
            'mail_skipped': 0,
            # Number of mails ignored because they were faulty.
            'mail_rejected': 0,
            # Number of valid mails ingested and retained for deduplication.
            'mail_kept': 0,
            # Number of unique mails (i.e. sets with one mail).
            'mail_unique': 0,
            # Number of duplicate mails (sum of mails in all duplicate sets).
            'mail_duplicates': 0,
            # Number of mails removed.
            'mail_deleted': 0,
            # Total number of duplicate sets.
            'set_total': 0,
            # Total number of unprocessed sets because mail is unique.
            'set_ignored': 0,
            # Total number of sets skipped as already deduplicated.
            'set_skipped': 0,
            # Number of sets ignored because they were faulty.
            'set_rejected_encoding': 0,
            'set_rejected_size': 0,
            'set_rejected_content': 0,
            # Number of valid sets successfuly deduplicated.
            'set_deduplicated': 0,
        })

    @staticmethod
    def canonical_path(path):
        """ Return a normalized, canonical path to a file or folder.

        Removes all symbolic links encountered in the path to detect natural
        mail and maildir duplicates on the fly.
        """
        return os.path.normcase(os.path.realpath(os.path.abspath(
            os.path.expanduser(path))))

    def add_source(self, source_path):
        """ Load up a mail source and compute hash for each mail found.

        If the path is a file, then it is considered as an ``mbox``. Else, if
        the provided path is a folder, it is parsed as a ``maildir``.
        """
        source_path = self.canonical_path(source_path)

        if os.path.isdir(source_path):
            logger.info("Opening {} as a maildir...".format(source_path))
            # Maildir parser requires a string, not a unicode, as path.
            mail_source = Maildir(str(source_path), factory=None, create=False)

        else:
            logger.info("Opening {} as an mbox...".format(source_path))
            mail_source = mbox(source_path, factory=None, create=False)

        logger.info("{} mails found.".format(len(mail_source)))

        # Register the mail source.
        self.sources[source_path] = mail_source

        # Setup the progress bar.
        def bar(iterable=None):
            """ Identity function to silence the progress bar. """
            return iterable

        # Override the pass-through bar() method with the progress bar widget.
        if self.conf.progress:
            bar = ProgressBar(
                widgets=[Percentage(), Bar()],
                max_value=len(mail_source),
                redirect_stderr=True, redirect_stdout=True)

        # Group mails by hash.
        for mail_id in bar(mail_source.iterkeys()):
            self.stats['mail_found'] += 1

            mail = Mail(source_path, mail_id, self.conf)

            try:
                mail_hash = mail.hash_key
            except (InsufficientHeadersError, MissingMessageID) as expt:
                logger.warning(
                    "Rejecting {}: {}".format(mail.path, expt.args[0]))
                self.stats['mail_rejected'] += 1
            else:
                logger.debug("Hash is {} for {}.".format(mail_hash, mail.path))
                # Use a set to deduplicate entries pointing to the same file.
                self.mails.setdefault(mail_hash, set()).add(mail)
                self.stats['mail_kept'] += 1

    def run(self):
        """ Run the deduplication process.

        We apply the removal strategy one duplicate set at a time to keep
        memory footprint low and make the log of actions easier to read.
        """
        if self.conf.strategy:
            logger.info(
                "The {} strategy will be applied on each duplicate set."
                "".format(self.conf.strategy))
        else:
            logger.warning("No removal strategy will be applied.")

        self.stats['set_total'] = len(self.mails)

        for hash_key, mail_set in self.mails.items():

            # Alter log level depending on set lenght.
            log_level = logger.debug if len(mail_set) == 1 else logger.info
            log_level("--- {} mails sharing hash {}".format(
                len(mail_set), hash_key))

            duplicates = DuplicateSet(hash_key, mail_set, self.conf)

            self.stats['mail_duplicates'] += duplicates.size

            # Fine-grained checks on mail differences.
            try:
                duplicates.check_differences()
            except SizeDiffAboveThreshold:
                self.stats['set_rejected_size'] += 1
                logger.warning(
                    "Reject set: mails are too dissimilar in size.")
                continue
            except ContentDiffAboveThreshold:
                self.stats['set_rejected_content'] += 1
                logger.warning(
                    "Reject set: mails are too dissimilar in content.")
                continue

            # Call the deduplication strategy.
            if self.conf.strategy:
                duplicates.apply_strategy(self.conf.strategy)

            # Merge stats resulting of actions on duplicate sets.
            self.stats += duplicates.stats

    def report(self):
        """ Print user-friendly statistics and metrics. """
        table = [["Mails", "Metric"]]
        table.append(["Found", self.stats['mail_found']])
        table.append(["Skipped", self.stats['mail_skipped']])
        table.append(["Rejected", self.stats['mail_rejected']])
        table.append(["Kept", self.stats['mail_kept']])
        table.append(["Unique", self.stats['mail_unique']])
        table.append(["Duplicates", self.stats['mail_duplicates']])
        table.append(["Deleted", self.stats['mail_deleted']])
        logger.info(tabulate(table, tablefmt='fancy_grid', headers='firstrow'))

        table = [["Duplicate sets", "Metric"]]
        table.append(["Total", self.stats['set_total']])
        table.append(["Ignored", self.stats['set_ignored']])
        table.append(["Skipped", self.stats['set_skipped']])
        table.append([
            "Rejected (bad encoding)",
            self.stats['set_rejected_encoding']])
        table.append([
            "Rejected (too dissimilar in size)",
            self.stats['set_rejected_size']])
        table.append([
            "Rejected (too dissimilar in content)",
            self.stats['set_rejected_content']])
        table.append(["Deduplicated", self.stats['set_deduplicated']])
        logger.info(tabulate(table, tablefmt='fancy_grid', headers='firstrow'))

        # Perform some high-level consistency checks on metrics.
        assert self.stats['mail_found'] == (
            self.stats['mail_skipped'] +
            self.stats['mail_rejected'] +
            self.stats['mail_kept'])
        assert self.stats['mail_kept'] >= self.stats['mail_unique']
        assert self.stats['mail_kept'] >= self.stats['mail_duplicates']
        assert self.stats['mail_kept'] >= self.stats['mail_deleted']
        assert self.stats['mail_kept'] == (
            self.stats['mail_unique'] +
            self.stats['mail_duplicates'])
        assert ((self.stats['mail_duplicates'] == 0) or
                (self.stats['mail_duplicates'] > self.stats['mail_deleted']))

        assert self.stats['set_ignored'] == self.stats['mail_unique']

        assert self.stats['set_total'] == (
            self.stats['set_ignored'] +
            self.stats['set_skipped'] +
            self.stats['set_rejected_encoding'] +
            self.stats['set_rejected_size'] +
            self.stats['set_rejected_content'] +
            self.stats['set_deduplicated'])
