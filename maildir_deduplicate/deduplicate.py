# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2016 Kevin Deldycke <kevin@deldycke.com>
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

import email
import hashlib
import os
import re
import textwrap
import time
from collections import namedtuple
from difflib import unified_diff
from mailbox import Maildir
from operator import attrgetter

from progressbar import Bar, Percentage, ProgressBar

from . import HEADERS, PY2, PY3, InsufficientHeadersError, logger

if PY3:
    basestring = (str, bytes)


class DuplicateSet(object):

    """ A duplicate set of mails sharing the same hash.

    Implements all deletion strategies applicable to a set of duplicate mails.
    """

    # A lightweight object-like structure to encapsulate a single mail and its
    # metadata.
    # TODO: Transform in a full object class to compute each field lazily and
    # to cache them on the fly.
    Mail = namedtuple('Mail', [
        # File path of the mail.
        'path',
        # Parsed content of the mail file. Is a email.message.Message instance.
        'message',
        # Raw size of the mail.
        'size',
        # Canonical timestamp.
        'timestamp',
    ])

    def __init__(self, hash_key, regexp=None, dry_run=True):
        self.hash_key = hash_key
        self.regexp = regexp
        self.dry_run = dry_run

        # Pool referencing all duplicated mails and their attributes.
        self.pool = set()

        # TODO: Keep a counter of action stats.
        # self.stats = Counter()

        logger.debug("{!r} created.".format(self))

    def __repr__(self):
        """ Print internal raw states for debugging. """
        return "<{} hash={}, size={}, dry_run={}>".format(
            self.__class__.__name__, self.hash_key, self.size, self.dry_run)

    @property
    def size(self):
        """ Return the size of the duplicate set. """
        return len(self.pool)

    def add_from_file(self, mail_path):
        """ Load a mail message from provided path and add it to the pool. """
        # Parse mail file content.
        with open(mail_path, 'rb') as mail_file:
            if PY2:
                message = email.message_from_file(mail_file)
            else:
                message = email.message_from_binary_file(mail_file)

        # Compute the normalized canonical timestamp of the mail.
        # TODO: currently returns the creation date of the mail file (i.e.
        # ctime) but might be changed in the future to get it from mail headers
        # instead.
        # XXX ctime does not refer to creation time on POSIX systems, but
        # rather the last time the inode data changed. Source:
        # http://userprimary.net/posts/2007/11/18
        # /ctime-in-unix-means-last-change-time-not-create-time/
        timestamp = os.path.getctime(mail_path)

        # Compute mail size. Size is computed as the lenght of the message
        # body, i.e. the payload of the mail stripped of all its headers, not
        # from the mail file persisting on the file-system.
        body = self.body_lines(message)
        size = len(''.join(body))

        # TODO: Allow customization of the way the size is computed, by getting
        # the file size instead for example.
        # size = os.path.getsize(mail_file)

        # Add mail to the pool.
        self.pool.add(self.Mail(
            path=mail_path, message=message, size=size, timestamp=timestamp))

    @property
    def subject(self):
        """ Normalized subject shared by all mails in the set.

        Only used for debugging and human-friendly logging.

        TODO: Cache it?
        """
        # Fetch subject from first message.
        subject = self.pool[0].message.get('Subject', '')
        subject, _ = re.subn(r'\s+', ' ', subject)
        return subject

    @staticmethod
    def body_lines(message):
        """ Return a normalized list of lines from message's body. """
        if not message.is_multipart():
            body = message.get_payload(None, decode=True)
        else:
            _, _, body = message.as_string().partition("\n\n")
        if isinstance(body, bytes):
            for enc in ['ascii', 'utf-8']:
                try:
                    body = body.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                body = message.get_payload(None, decode=False)
        return body.splitlines(True)

    def delete(self, mail):
        """ Delete a mail fron the filesystem. """
        if self.dry_run:
            logger.info("Skip deletion of {!r}.".format(mail))
            return

        logger.info("Deleting {!r}...".format(mail))
        # XXX Investigate the use of maildir's .remove instead. See: https:
        # //github.com/python/cpython/blob/origin/2.7/Lib/mailbox.py#L329-L331
        os.unlink(mail.path)

    # TODO: Factorize code structure common to all strategy.

    def delete_older(self):
        """ Delete all older duplicates.

        Only keeps the subset sharing the most recent timestamp.
        """
        newest_timestamp = max(map(attrgetter('timestamp'), self.pool))
        logger.info(
            "Delete all mails strictly older than the {} timestamp...".format(
                newest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.timestamp < newest_timestamp]
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
        oldest_timestamp = min(map(attrgetter('timestamp'), self.pool))
        logger.info(
            "Delete all mails sharing the oldest {} timestamp...".format(
                oldest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.timestamp == oldest_timestamp]
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
        oldest_timestamp = min(map(attrgetter('timestamp'), self.pool))
        logger.info(
            "Delete all mails strictly newer than the {} timestamp...".format(
                oldest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.timestamp > oldest_timestamp]
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
        newest_timestamp = max(map(attrgetter('timestamp'), self.pool))
        logger.info(
            "Delete all mails sharing the newest {} timestamp...".format(
                newest_timestamp))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.timestamp == newest_timestamp]
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
        biggest_size = max(map(attrgetter('size'), self.pool))
        logger.info(
            "Delete all mails strictly smaller than {} bytes...".format(
                biggest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.size < biggest_size]
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
        smallest_size = min(map(attrgetter('size'), self.pool))
        logger.info(
            "Delete all mails sharing the smallest size of {} bytes...".format(
                smallest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.size == smallest_size]
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
        smallest_size = min(map(attrgetter('size'), self.pool))
        logger.info(
            "Delete all mails strictly bigger than {} bytes...".format(
                biggest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.size > smallest_size]
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
        biggest_size = max(map(attrgetter('size'), self.pool))
        logger.info(
            "Delete all mails sharing the biggest size of {} bytes...".format(
                biggest_size))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if mail.size == biggest_size]
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
            "Delete all mails with file path matching the {} regexp...".format(
                self.regexp.pattern))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool if re.search(self.regexp, mail.path)]
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
            "Delete all mails with file path not matching the {} regexp..."
            "".format(self.regexp.pattern))
        # Select candidates for deletion.
        candidates = [
            mail for mail in self.pool
            if not re.search(self.regexp, mail.path)]
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

    def __init__(self, strategy, regexp, dry_run, show_diffs, use_message_id,
                 size_threshold, diff_threshold, progress=True):
        # All mails grouped by hashes.
        self.mails = {}
        # Total count of mails found in all maildirs.
        self.mail_count = 0

        # Global config.
        self.strategy = strategy
        self.regexp = regexp
        self.dry_run = dry_run
        self.use_message_id = use_message_id
        self.progress = progress

        # XXX Unsupported options.
        # TODO: re-integrate these options and features.
        self.show_diffs = show_diffs
        self.size_threshold = size_threshold
        self.diff_threshold = diff_threshold

        # Deduplication statistics.
        # TODO: use a Counter
        self.duplicates = 0
        self.sets = 0
        self.removed = 0
        self.sizes_too_dissimilar = 0
        self.diff_too_big = 0

    @staticmethod
    def canonical_path(path):
        """ Return a normalized, canonical path to a file or folder.

        Removes all symbolic links encountered in the path to detect natural
        mail and maildir duplicates on the fly.
        """
        return os.path.normcase(os.path.realpath(os.path.abspath(
            os.path.expanduser(path))))

    def add_maildir(self, maildir_path):
        """ Load up a maildir and compute hash for each mail found. """
        maildir_path = self.canonical_path(maildir_path)
        logger.info("Opening maildir folder at {!r} ...".format(maildir_path))
        # Maildir parser requires a string, not a unicode, as path.
        maildir = Maildir(str(maildir_path), factory=None, create=False)

        # Group folders by hash.
        logger.info("{} mails found.".format(len(maildir)))
        if self.progress:
            bar = ProgressBar(widgets=[Percentage(), Bar()],
                              max_value=len(maildir), redirect_stderr=True,
                              redirect_stdout=True)
        else:
            def bar(x):
                return x

        for mail_id, message in bar(maildir.iteritems()):
            mail_path = self.canonical_path(os.path.join(
                maildir._path, maildir._lookup(mail_id)))
            try:
                mail_hash, header_text = self.compute_hash(
                    mail_path, message, self.use_message_id)
            except InsufficientHeadersError as e:
                logger.warning(
                    "Ignoring problematic {}: {}".format(mail_path, e.args[0]))
            else:
                logger.debug(
                    "Hash is {} for mail {!r}.".format(mail_hash, mail_id))
                # Use a set to deduplicate entries pointing to the same file.
                self.mails.setdefault(mail_hash, set()).add(mail_path)
                self.mail_count += 1

    @classmethod
    def compute_hash(cls, mail_path, message, use_message_id):
        """ Compute the canonical hash of a mail.

        This hash will be used to group identical mails under the same unique
        ID.

        Return a tuple of the hash string and canonical headers.
        """
        if use_message_id:
            message_id = message.get('Message-Id')
            if message_id:
                return message_id.strip(), ''
            header_text = cls.header_text(message)
            logger.warning(
                "No Message-ID in {}: {}".format(mail_path, header_text))
        canonical_headers_text = cls.canonical_headers(message)
        return (
            hashlib.sha224(canonical_headers_text.encode('utf-8')).hexdigest(),
            canonical_headers_text)

    @staticmethod
    def header_text(message):
        return ''.join(
            '{}: {}\n'.format(header, message[header])
            for header in HEADERS
            if message[header] is not None)

    @classmethod
    def canonical_headers(cls, message):
        """ Copy selected headers into a new string. """
        canonical_headers = ''

        for header in HEADERS:
            if header not in message:
                continue

            for value in message.get_all(header):
                canonical_value = cls.canonical_header_value(header, value)
                if re.search('\S', canonical_value):
                    canonical_headers += '{}: {}\n'.format(
                        header, canonical_value)

        if len(canonical_headers) > 50:
            return canonical_headers

        # We should have at absolute minimum 3 or 4 headers, e.g.
        # From/To/Date/Subject; if not, something went badly wrong.

        if len(canonical_headers) == 0:
            raise InsufficientHeadersError("No canonical headers found")

        err = textwrap.dedent("""\
            Not enough data from canonical headers to compute reliable hash!
            Headers:
            --------- 8< --------- 8< --------- 8< --------- 8< ---------
            {}
            --------- 8< --------- 8< --------- 8< --------- 8< ---------""")
        raise InsufficientHeadersError(err.format(canonical_headers))

    @classmethod
    def canonical_header_value(cls, header, value):
        header = header.lower()
        # Problematic when reading utf8 emails
        # this will ensure value is always string
        if (not type(value) is str):
            value = value.encode()
        value = re.sub('\s+', ' ', value).strip()

        # Trim Subject prefixes automatically added by mailing list software,
        # since the mail could have been cc'd to multiple lists, in which case
        # it will receive a different prefix for each, but this shouldn't be
        # treated as a real difference between duplicate mails.
        if header == 'subject':
            subject = value
            while True:
                m = re.match("([Rr]e: )*(\[\w[\w_-]+\w\] )+(?s)(.+)", subject)
                if not m:
                    break
                subject = m.group(3)
                # show_progress("Trimmed Subject to %s" % subject)
            return subject
        elif header == 'content-type':
            # Apparently list servers actually munge Content-Type
            # e.g. by stripping the quotes from charset="us-ascii".
            # Section 5.1 of RFC2045 says that either form is valid
            # (and they are equivalent).
            #
            # Additionally, with multipart/mixed, boundary delimiters can
            # vary by recipient.  We need to allow for duplicates coming
            # from multiple recipients, since for example you could be
            # signed up to the same list twice with different addresses.
            # Or maybe someone bounces you a load of mail some of which is
            # from a mailing list you're both subscribed to - then it's
            # still useful to be able to eliminate duplicates.
            return re.sub(';.*', '', value)
        elif header == 'date':
            # Date timestamps can differ by seconds or hours for various
            # reasons, so let's only honour the date for now.
            try:
                parsed = email.utils.parsedate_tz(value)
                if not parsed:
                    raise TypeError
            # If parsedate_tz cannot parse the date.
            except (TypeError, ValueError):
                return value
            utc_timestamp = email.utils.mktime_tz(parsed)
            try:
                return time.strftime(
                    '%Y/%m/%d UTC', time.gmtime(utc_timestamp))
            except ValueError:
                return value
        elif header == 'to':
            # Sometimes email.parser strips the <> brackets from a To:
            # header which has a single address.  I have seen this happen
            # for only one mail in a duplicate pair.  I'm not sure why
            # (presumably the parser uses email.utils.unquote somewhere in
            # its code path which was only triggered by that mail and not
            # its sister mail), but to be safe, we should always strip the
            # <> brackets to avoid this difference preventing duplicate
            # detection.
            if re.match("^<[^<>,]+>$", value):
                return email.utils.unquote(value)

        return value

    def run(self):
        """ Run the deduplication process.

        We apply the removal strategy one duplicate set at a time to keep
        memory footprint low and make the log of actions easier to read.
        """
        logger.info("Start the deduplication process.")

        # Transform strategy keyword into its method ID, and check an
        # implementation is available.
        # TODO: move its check in unit-tests.
        # TODO: check it is a method.
        strategy_method_id = self.strategy.replace('-', '_')
        if not hasattr(DuplicateSet, strategy_method_id):
            raise NotImplementedError(
                "DuplicateSet.{}() method.".format(strategy_method_id))

        logger.info(
            "Applyng the {} removal strategy on each duplicate set...".format(
                self.strategy))

        for hash_key, mail_path_set in self.mails.items():

            logger.debug("Loading duplicate set sharing the {} hash.".format(
                hash_key))
            if len(mail_path_set) == 1:
                logger.debug("Skip: only one message found.")
                continue

            duplicates = DuplicateSet(
                hash_key, regexp=self.regexp, dry_run=self.dry_run)
            for mail_path in mail_path_set:
                duplicates.add_from_file(mail_path)

            logger.debug(
                "Initialized duplicate set of {} mails sharing the {} hash."
                "".format(duplicates.size, duplicates.hash_key))

            getattr(duplicates, strategy_method_id)()


        #    too_dissimilar = self.messages_too_dissimilar(
        #        hash_key, sorted_messages_size)
        #    if too_dissimilar == 'size':
        #        self.sizes_too_dissimilar += 1
        #        continue
        #    elif too_dissimilar == 'diff':
        #        self.diff_too_big += 1
        #        continue
        #    elif too_dissimilar is False:
        #        pass
        #    else:
        #        raise ValueError(
        #            "Unexpected value {!r} for too_dissimilar".format(
        #                too_dissimilar))

    def messages_too_dissimilar(self, hash_key, sizes):
        largest_size, largest_file, largest_message = sizes[0]
        largest_lines = self.body_lines(largest_message)

        for size, mail_file, message in sizes[1:]:
            size_difference = largest_size - size
            lines = self.body_lines(message)

            if (self.size_threshold >= 0) and (
                    size_difference > self.size_threshold):
                logger.info(
                    "For hash key {}, sizes differ by {} > {} bytes:\n"
                    "  {} {}\n  {} {}".format(
                        hash_key, size_difference, self.size_threshold,
                        size, mail_file,
                        largest_size, largest_file))
                if self.show_diffs:
                    self.print_diff(
                        lines, largest_lines, mail_file, largest_file)
                return 'size'

            text_difference = self.text_diff(lines, largest_lines)
            if self.diff_threshold >= 0 and len(
                    text_difference) > self.diff_threshold:
                logger.info(
                    "Diff between duplicate messages with hash key {} was "
                    "{} > {} bytes.".format(
                        hash_key, len(text_difference), self.diff_threshold))
                if len(largest_lines) > 8192:
                    logger.info("Not printing diff for this duplicate set, "
                                "it is too large")
                else:
                    self.print_diff(lines, largest_lines, mail_file,
                                    largest_file)
                return 'diff'

            elif len(text_difference) == 0:
                if self.show_diffs:
                    logger.info("Diff produced no differences")

            else:
                # Difference is inside threshold
                if self.show_diffs:
                    self.print_diff(
                        lines, largest_lines, mail_file, largest_file)

        return False

    @staticmethod
    def text_diff(lines, largest_lines):
        return ''.join(unified_diff(
            lines, largest_lines,
            # Ignore difference in filename lenghts and timestamps.
            fromfile='a', tofile='b',
            fromfiledate='', tofiledate='',
            n=0, lineterm='\n'))

    @staticmethod
    def print_diff(from_lines, to_lines, from_file, to_file):
        logger.info(''.join(unified_diff(
            from_lines, to_lines,
            fromfile='Body of {}'.format(from_file),
            tofile='Body of {}'.format(to_file),
            fromfiledate='{:0.2f}'.format(os.path.getmtime(from_file)),
            tofiledate='{:0.2f}'.format(os.path.getmtime(to_file)),
            n=0, lineterm='\n')))

    def report(self):
        total = " in {} set{} from a total of {} mails.".format(
            self.sets, 's' if self.sets > 1 else '', self.mail_count)
        if self.removed > 0:
            results = "Removed {} of {} duplicates found".format(
                self.removed, self.duplicates)
            if self.dry_run:
                results = "Would have {}".format(results)
        else:
            results = "Found {} duplicates".format(self.duplicates)

        logger.info("{}\n{}".format(results, total))

        if self.sizes_too_dissimilar > 0:
            logger.info(
                "{} potential duplicates were rejected as being too "
                "dissimilar in size.".format(self.sizes_too_dissimilar))

        if self.diff_too_big > 0:
            logger.info(
                "{} potential duplicates were rejected as being too "
                "dissimilar in contents.".format(self.diff_too_big))
