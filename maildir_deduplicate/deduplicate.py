# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Kevin Deldycke <kevin@deldycke.com>
#                         Adam Spiers <adam@spiers.net>
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
    division, print_function, absolute_import, unicode_literals
)

import os
import re
import hashlib
import email
import time
from mailbox import Maildir
from difflib import unified_diff

from . import (
    HEADERS, SMALLER, OLDER, NEWER, MATCHING, NOT_MATCHING,
    InsufficientHeadersError
)


class Deduplicate(object):

    def __init__(self, strategy, regexp, dry_run, show_diffs, use_message_id,
                 size_threshold, diff_threshold):
        # All mails grouped by hashes.
        self.mails = {}
        # Total count of mails found in all maildirs.
        self.mail_count = 0

        # Global config.
        self.strategy = strategy
        self.regexp = regexp
        self.dry_run = dry_run
        self.show_diffs = show_diffs
        self.use_message_id = use_message_id
        self.size_threshold = size_threshold
        self.diff_threshold = diff_threshold

        # Deduplication statistics.
        self.duplicates = 0
        self.sets = 0
        self.removed = 0
        self.sizes_too_dissimilar = 0
        self.diff_too_big = 0

    def add_maildir(self, maildir_path):
        """ Load up a maildir add compute hash for each mail their contain. """
        maildir = Maildir(maildir_path, create=False)
        # Collate folders by hash.
        print("Processing {} mails in {}".format(len(maildir), maildir._path))
        for mail_id, message in maildir.iteritems():
            mail_file = os.path.join(maildir._path, maildir._lookup(mail_id))
            try:
                mail_hash, header_text = self.compute_hash(
                    mail_file, message, self.use_message_id)
            except InsufficientHeadersError as e:
                print("WARNING: ignoring problematic {}: {}".format(
                    mail_file, e.args[0]))
            else:
                if self.mail_count > 0 and self.mail_count % 100 == 0:
                    print(".")
                # print("Hash is {} for mail {!r}.".format(mail_hash, mail_id))
                if mail_hash not in self.mails:
                    self.mails[mail_hash] = []

                self.mails[mail_hash].append((mail_file, message))
                self.mail_count += 1

    @classmethod
    def compute_hash(cls, mail_file, message, use_message_id):
        if use_message_id:
            message_id = message.get('Message-Id')
            if message_id:
                return message_id.strip(), ''
            header_text = cls.header_text(message)
            print("WARNING: no Message-ID in {}: {}".format(
                mail_file, header_text))
        canonical_headers_text = cls.canonical_headers(mail_file, message)
        return hashlib.sha224(
            canonical_headers_text).hexdigest(), canonical_headers_text

    @staticmethod
    def header_text(mail):
        return ''.join(
            '{}: {}\n'.format(header, mail[header])
            for header in HEADERS
            if mail[header] is not None)

    @classmethod
    def canonical_headers(cls, mail_file, mail):
        """ Copy selected headers into a new string. """
        canonical_headers = ''

        for header in HEADERS:
            if header not in mail:
                continue

            for value in mail.get_all(header):
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

        err = """Not enough data from canonical headers to compute reliable hash!
Headers:
--------- 8< --------- 8< --------- 8< --------- 8< --------- 8< ---------
{}--------- 8< --------- 8< --------- 8< --------- 8< --------- 8< ---------"""
        raise InsufficientHeadersError(err.format(canonical_headers))

    @classmethod
    def canonical_header_value(cls, header, value):
        header = header.lower()
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
            except (TypeError, ValueError):  # if parsedate_tz cannot parse the date
                return value
            utc_timestamp = email.utils.mktime_tz(parsed)
            try:
                return time.strftime('%Y/%m/%d UTC', time.gmtime(utc_timestamp))
            except ValueError:
                return value
            return date_only
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
        """ Run the deduplication process. """
        for hash_key, messages in self.mails.iteritems():
            # Skip unique mails.
            if len(messages) == 1:
                continue

            subject = messages[0][1].get('Subject', '')
            subject, count = re.subn('\s+', ' ', subject)
            print("Subject: {}".format(subject))

            if self.strategy == OLDER:
                sorted_messages_ctime = self.time_sort(messages, False)
            elif self.strategy == NEWER:
                sorted_messages_ctime = self.time_sort(messages, True)

            sorted_messages_size = self.size_sort(messages)

            too_dissimilar = self.messages_too_dissimilar(
                hash_key, sorted_messages_size)
            if too_dissimilar == 'size':
                self.sizes_too_dissimilar += 1
                continue
            elif too_dissimilar == 'diff':
                self.diff_too_big += 1
                continue
            elif too_dissimilar is False:
                pass
            else:
                raise ValueError(
                    "Unexpected value {!r} for too_dissimilar".format(
                        too_dissimilar))

            self.duplicates += len(messages) - 1
            self.sets += 1

            if self.strategy in [OLDER, NEWER]:
                self.removed += self.process_duplicate_set(
                    sorted_messages_ctime)
            else:
                self.removed += self.process_duplicate_set(
                    sorted_messages_size)

    def process_duplicate_set(self, duplicate_set):
        i = 0
        removed = 0

        doomed = self.choose_duplicates_to_remove(duplicate_set)
        # Safety valve.
        if len(doomed) == len(duplicate_set):
            raise ValueError("Tried to remove whole duplicate set.")

        for size, mail_file, message in duplicate_set:
            i += 1
            prefix = "  "
            if mail_file in doomed:
                prefix = "removed"
                if not self.dry_run:
                    os.unlink(mail_file)
                removed += 1
            else:
                prefix = "left   "
            print("{} {} {} {}".format(prefix, i, size, mail_file))

        return removed

    def choose_duplicates_to_remove(self, duplicate_set):
        doomed = {}

        for i, duplicate in enumerate(duplicate_set):
            size, mail_file, message = duplicate
            if self.strategy in [SMALLER, OLDER, NEWER]:
                if i > 0:
                    doomed[mail_file] = 1
            elif self.strategy == MATCHING:
                if re.search(self.regexp, mail_file):
                    doomed[mail_file] = 1
            elif self.strategy == NOT_MATCHING:
                if not re.search(self.regexp, mail_file):
                    doomed[mail_file] = 1

        # Safety valve.
        if len(doomed) == len(duplicate_set):
            if self.strategy in [MATCHING, NOT_MATCHING]:
                print(
                    "/{}/ matched whole set; not removing any duplicates."
                    "".format(self.regexp.pattern))
            else:
                raise ValueError(
                    "Removal strategy tried to remove all duplicates in set.")
            return {}

        return doomed

    @staticmethod
    def time_sort(messages, old_to_new):
        ctimes = []
        for mail_file, message in messages:
            ctime = os.path.getctime(mail_file)
            ctimes.append((ctime, mail_file, message))

        def _sort_by_ctime_new_to_old(a, b):
            return cmp(b[0], a[0])

        def _sort_by_ctime_old_to_new(a, b):
            return cmp(a[0], b[0])

        # Order from oldest to newest.
        if old_to_new:
            ctimes.sort(cmp=_sort_by_ctime_old_to_new)
        # Order from newest to oldest.
        else:
            ctimes.sort(cmp=_sort_by_ctime_new_to_old)

        return ctimes

    @classmethod
    def size_sort(cls, messages):
        sizes = []
        for mail_file, message in messages:
            body = cls.get_lines_from_message_body(message)
            # size = os.path.getsize(mail_file)
            size = len(''.join(body))
            sizes.append((size, mail_file, message))

        def _sort_by_size(a, b):
            return cmp(b[0], a[0])

        sizes.sort(cmp=_sort_by_size)
        return sizes

    @staticmethod
    def get_lines_from_message_body(message):
        if not message.is_multipart():
            body = message.get_payload(None, decode=True)
        else:
            header_text, sep, body = message.as_string().partition("\n\n")
        return body.splitlines(True)

    def messages_too_dissimilar(self, hash_key, sizes):
        largest_size, largest_file, largest_message = sizes[0]
        largest_lines = self.get_lines_from_message_body(largest_message)

        for size, mail_file, message in sizes[1:]:
            size_difference = largest_size - size
            lines = self.get_lines_from_message_body(message)

            if (self.size_threshold >= 0) and (
                    size_difference > self.size_threshold):
                print(
                    "For hash key {}, sizes differ by {} > {} bytes:\n"
                    "  {} {}\n  {} {}".format(
                        hash_key, size_difference, size_threshold,
                        size, mail_file,
                        largest_size, largest_file))
                if self.show_diffs:
                    self.print_diff(
                        lines, largest_lines, mail_file, largest_file)
                return 'size'

            text_difference = self.text_diff(lines, largest_lines)
            if self.diff_threshold >= 0 and len(
                    text_difference) > self.diff_threshold:
                print(
                    "Diff between duplicate messages with hash key {} was "
                    "{} > {} bytes.".format(
                        hash_key, len(text_difference), self.diff_threshold))
                self.print_diff(lines, largest_lines, mail_file, largest_file)
                return 'diff'

            elif len(text_difference) == 0:
                if self.show_diffs:
                    print("Diff produced no differences")

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
        print(''.join(unified_diff(
            from_lines, to_lines,
            fromfile='Body of {}'.format(from_file),
            tofile='Body of {}'.format(to_file),
            fromfiledate=os.path.getmtime(from_file),
            tofiledate=os.path.getmtime(to_file),
            n=0, lineterm='\n')))

    def report(self):
        total = " in {} set{} from a total of {} mails.".format(
            self.sets, 's' if self.sets > 1 else '', mail_count)
        if self.removed > 0:
            results = "Removed {} of {} duplicates found".format(
                self.removed, self.duplicates)
            if opts.dry_run:
                results = "Would have {}".format(results)
        else:
            results = "Found {} duplicates".format(self.duplicates)

        print("{}\n{}".format(results, total))

        if self.sizes_too_dissimilar > 0:
            print(
                "{} potential duplicates were rejected as being too dissimilar "
                "in size.".format(self.sizes_too_dissimilar))

        if self.diff_too_big > 0:
            print(
                "{} potential duplicates were rejected as being too dissimilar "
                "in contents.".format(self.diff_too_big))
