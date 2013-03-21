#!/usr/bin/python

##############################################################################
#
# Copyright (C) 2010-2011 Kevin Deldycke <kevin@deldycke.com>
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
#
##############################################################################

"""
    This script reads all mails in a given list of maildir folders and
    subfolders, then automatically detects, lists, and optionally
    deletes any duplicate mails.

    Duplicate detection is done by cherry-picking certain headers, in
    some cases doing some minor tweaking of the values to reduce them
    to a canonical form, and then computing a digest of those headers
    concatenated together.

    Note that we deliberately limit this to certain headers due to the
    effects that mailing list software can have on not only the mail
    header but the body; it can potentially:

      - append a footer to a list body, thus changing the
        Content-Length header

      - create a new path described by the Received headers which would
        not be contained in any copy of the mail saved locally at
        the time it was sent to the list

      - munge the Reply-To header even though it's a bad idea

      - add plenty of other random headers which a copy saved locally at
        sending-time would not have, such as X-Mailman-Version,
        Precedence, X-BeenThere, List-*, Sender, Errors-To, and so on.

      - add a prefix to the Subject header

    Another difficulty is the lack of guarantee that Message-ID is
    unique or even present.  Yes, certain broken mail servers which
    must remain nameless are guilty of this :-(

    For added protection against accidentally removing mails due to
    false positives, duplicates are verified by comparing body sizes
    and also diff'ing the contents.  If the sizes or contents differ
    by more than a threshold, they are not counted as duplicates.

    Tested on MacOS X 10.6 with Python 2.6.2 and Linux with Python
    2.6.0 and 2.7.2.
"""

import os
import re
import sys
import hashlib
import email
import time
from optparse     import OptionParser
from mailbox      import Maildir
from email.parser import Parser
from difflib      import unified_diff

# List of mail headers to use when computing the hash of a mail.
HEADERS = [
    'Date',
    'From',
    'To',
    # No Cc since mailman apparently sometimes trims list members
    # from the Cc header to avoid sending duplicates:
    #   http://mail.python.org/pipermail/mailman-developers/2002-September/013233.html
    # but this means that copies of mail reflected back from the list
    # server will have a different Cc to the copy saved by the MUA
    # at send-time.
    #
    # No Bcc since copies of the mail saved by the MUA at send-time
    # will have Bcc, but copies reflected back from the list server
    # won't.
    #
    # No Reply-To since a mail could be Cc'd to two lists with
    # different Reply-To munging options set.
    'Subject',
    'Message-ID',
    'MIME-Version',
    'Content-Type',
    'Content-Disposition',
    'User-Agent',
    'X-Priority',
]

# Since we're ignoring the Content-Length header for the reasons
# stated above, we limit the allowed difference between the sizes of
# the message payloads.  If this is exceeded, a warning is issued and
# the messages are not considered duplicates, because this could point
# to message corruption somewhere, or a false positive.  Note that the
# headers are not counted towards this threshold, because many headers
# can be added by mailing list software such as mailman, or even by
# the process of sending the mail through various MTAs - one copy
# could have been stored by the sender's MUA prior to sending, without
# any Received: headers, and another copy could be reflected back via
# a Cc-to-self mechanism or mailing list server.  But this threshold
# has to be at least large enough to allow for footers added by
# mailing list servers.
DEFAULT_SIZE_DIFFERENCE_THRESHOLD = 512 # bytes

# Similarly, we generated unified diffs of duplicates and ensure that
# the diff is not greater than a certain size.
DEFAULT_DIFF_THRESHOLD = 768 # bytes

def parse_args():
    parser = OptionParser(
        usage = '%prog [OPTIONS] [MAILDIR [MAILDIR ...]]',
        description = 'Detect/remove duplicates from maildir folders',
    )

    parser.add_option(
        '-d', '--remove-smaller', action = 'store_true',
        help = 'Remove all but largest duplicate in each duplicate set'
    )
    parser.add_option(
        '-r', '--remove-matching', type = 'string', metavar='REGEXP',
        help = 'Remove duplicates whose file path matches REGEXP'
    )
    parser.add_option(
        '-R', '--remove-not-matching', type = 'string', metavar='REGEXP',
        help = 'Remove duplicates whose file path does not match REGEXP'
    )
    parser.add_option(
        '-n', '--dry-run', action = 'store_true',
        help = "Don't actually remove anything; just show what would be removed."
    )
    parser.add_option(
        '-s', '--show-diffs', action = 'count',
        help = "Show diffs between duplicates even if " \
               "they're within the thresholds"
    )
    parser.add_option(
        '-i', '--message-id', action = 'store_true',
        help = 'Use Message-ID header as hash key ' \
               '(not recommended - the default is to compute a digest ' \
               'of the whole header with selected headers removed)'
    )
    parser.add_option(
        '-S', '--size-threshold', type = 'int', metavar='BYTES',
        default = DEFAULT_SIZE_DIFFERENCE_THRESHOLD,
        help = 'Specify maximum allowed difference ' \
               'between size of duplicates. ' \
               'Default is %default; set -1 for no threshold.'
    )
    parser.add_option(
        '-D', '--diff-threshold', type = 'int', metavar='BYTES',
        default = DEFAULT_DIFF_THRESHOLD,
        help = 'Specify maximum allowed size of unified diff ' \
               'between duplicates. ' \
               'Default is %default; set -1 for no threshold.'
    )
    parser.add_option(
        '-H', '--hash-pipe', action = 'store_true',
        help = "Take a single mail message texted piped from STDIN "  \
               "and show its canonicalised form and hash thereof. "   \
               "This is useful for debugging why two messages don't " \
               "have the same hash when you expect them to (or vice-versa)."
    )

    opts, maildirs = parser.parse_args()

    if len(maildirs) == 0 and not opts.hash_pipe:
        usage_error(parser, "Must specify at least one maildir folder")

    if count_removal_strategies(opts) > 1:
        usage_error(parser, "Cannot specify multiple removal strategies.")

    if opts.remove_matching:
        opts.remove_matching = re.compile(opts.remove_matching)

    return opts, maildirs

def count_removal_strategies(opts):
    count = 0
    for strategy in ('smaller', 'matching', 'not_matching'):
        if getattr(opts, "remove_%s" % strategy):
            count += 1
    return count

def usage_error(parser, error_msg):
    sys.stderr.write("Error: %s\n\n" % error_msg)
    parser.print_help()
    sys.exit(2)

def get_canonical_headers(mail):
    '''Copy selected headers into a new string.'''
    canonical_headers = ''

    for header in HEADERS:
        if header not in mail:
            continue

        for value in mail.get_all(header):
            canonical_value = get_canonical_header_value(header, value)
            if re.search('\S', canonical_value):
                canonical_headers += '%s: %s\n' % (header, canonical_value)

    return canonical_headers

def get_canonical_header_value(header, value):
    header = header.lower()
    value = re.sub('\s+', ' ', value)

    # Trim Subject prefixes automatically added by mailing list software,
    # since the mail could have been cc'd to multiple lists, in which case
    # it will receive a different prefix for each, but this shouldn't be
    # treated as a real difference between duplicate mails.
    if header == 'subject':
        m = re.match("(\[\w[\w_-]+\w\] )+(?s)(.+)", value)
        if m:
            #show_progress("\nTrimmed '%s' from %s" % (m.group(1), value))
            return m.group(2)
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
            utc_timestamp = email.utils.mktime_tz(parsed)
        except TypeError: # if parsedate_tz cannot parse the date
            return value

        return time.strftime('%Y/%m/%d UTC', time.gmtime(utc_timestamp))
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

def compute_hash_key(message, use_message_id):
    header_text = get_header_text(message)

    if use_message_id:
        message_id = message.get('Message-Id')
        if message_id:
            return message_id
        sys.stderr.write("\n\nWARNING: no Message-ID in:\n" + header_text)
        #sys.exit(3)

    canonical_headers_text = get_canonical_headers(message)
    return hashlib.sha224(canonical_headers_text).hexdigest(), canonical_headers_text

def get_header_text(mail):
    header_text = ''.join('%s: %s\n' % (header, mail[header]) for header in HEADERS
                          if mail[header] is not None)
    return header_text

def collate_folder_by_hash(mails_by_hash, mail_folder, use_message_id):
    mail_count = 0
    path = re.sub(os.getenv('HOME'), '~', mail_folder._path)
    sys.stderr.write("Processing %s mails in %s " % \
                         (len(mail_folder), path))
    for mail_id, message in mail_folder.iteritems():
        mail_hash, header_text = compute_hash_key(message, use_message_id)
        if mail_count > 0 and mail_count % 100 == 0:
            sys.stderr.write(".")
        #show_progress("  Hash is %s for mail %r" % (mail_hash, mail_id))
        if mail_hash not in mails_by_hash:
            mails_by_hash[mail_hash] = [ ]

        mail_file = os.path.join(mail_folder._path, mail_folder._lookup(mail_id))
        mails_by_hash[mail_hash].append((mail_file, message))
        mail_count += 1

    sys.stderr.write("\n")

    return mail_count

def find_duplicates(mails_by_hash, opts):
    duplicates = 0
    sets = 0
    removed = 0
    sizes_too_dissimilar = 0
    diff_too_big = 0
    for hash_key, messages in mails_by_hash.iteritems():
        if len(messages) == 1:
            #print "unique:", messages[0]
            continue

        subject = messages[0][1].get('Subject', '')
        subject, count = re.subn('\s+', ' ', subject)
        print "\nSubject: " + subject

        sizes = sort_messages_by_size(messages)
        too_dissimilar = messages_too_dissimilar(hash_key, sizes, opts)
        if too_dissimilar == 'size':
            sizes_too_dissimilar += 1
            continue
        elif too_dissimilar == 'diff':
            diff_too_big += 1
            continue
        elif too_dissimilar is False:
            pass
        else:
            error = "BUG: unexpected value '%s' for too_dissimilar"
            fatal(error % too_dissimilar)

        duplicates += len(messages) - 1
        sets += 1

        removed += process_duplicate_set(sizes, opts)

    return duplicates, sizes_too_dissimilar, diff_too_big, removed, sets

def process_duplicate_set(duplicate_set, opts):
    i = 0
    removed = 0

    if opts.remove_smaller or opts.remove_matching or opts.remove_not_matching:
        doomed = choose_duplicates_to_remove(duplicate_set, opts)
        # safety valve
        if len(doomed) == len(duplicate_set):
            fatal("BUG: tried to remove whole duplicate set!")

    for size, mail_file, message in duplicate_set:
        i += 1
        prefix = "  "
        if opts.remove_smaller or opts.remove_matching:
            if mail_file in doomed:
                prefix = "removed"
                if not opts.dry_run:
                    os.unlink(mail_file)
                removed += 1
            else:
                prefix = "left   "
        print "%s %2d %d %s" % (prefix, i, size, mail_file)

    return removed

def choose_duplicates_to_remove(duplicate_set, opts):
    doomed = { }

    for i, duplicate in enumerate(duplicate_set):
        size, mail_file, message = duplicate
        if opts.remove_smaller:
            if i > 0:
                doomed[mail_file] = 1
        elif opts.remove_matching:
            if re.search(opts.remove_matching, mail_file):
                doomed[mail_file] = 1
        elif opts.remove_not_matching:
            if not re.search(opts.remove_not_matching, mail_file):
                doomed[mail_file] = 1

    # safety valve
    if len(doomed) == len(duplicate_set):
        if opts.remove_matching:
            sys.stderr.write("/%s/ matched whole set; not removing any duplicates.\n" %
                             opts.remove_matching.pattern)
        elif opts.remove_not_matching:
            sys.stderr.write("/%s/ matched whole set; not removing any duplicates.\n" %
                             opts.remove_not_matching.pattern)
        else:
            fatal("BUG: removal strategy tried to remove all duplicates in set!")
        return { }

    return doomed

def sort_messages_by_size(messages):
    sizes = [ ]
    for mail_file, message in messages:
        body = get_lines_from_message_body(message)
        #size = os.path.getsize(mail_file)
        size = len("".join(body))
        sizes.append((size, mail_file, message))
    def _sort_by_size(a, b):
        return cmp(b[0], a[0])
    sizes.sort(cmp = _sort_by_size)
    return sizes

def get_lines_from_message_body(message):
    header_text, sep, body = message.as_string().partition("\n\n")
    return body.splitlines(True)

def messages_too_dissimilar(hash_key, sizes, opts):
    diff_threshold = opts.diff_threshold
    size_threshold = opts.size_threshold

    largest_size, largest_file, largest_message = sizes[0]
    largest_lines = get_lines_from_message_body(largest_message)

    for size, mail_file, message in sizes[1:]:
        size_difference = largest_size - size
        lines = get_lines_from_message_body(message)

        if size_threshold >= 0 and size_difference > size_threshold:
            msg = "For hash key %s, sizes differ by %d > %d bytes:\n" \
                  "  %d %s\n  %d %s" % \
                  (hash_key, size_difference, size_threshold,
                   size, mail_file,
                   largest_size, largest_file)
            show_progress(msg)
            if opts.show_diffs:
                show_friendly_diff(lines, largest_lines, mail_file, largest_file)
            return 'size'

        text_difference = get_text_difference(lines, largest_lines)
        if diff_threshold >= 0 and len(text_difference) > diff_threshold:
            msg = "diff between duplicate messages with hash key %s " \
                  "was %d > %d bytes\n" % \
                  (hash_key,
                   len(text_difference), diff_threshold)
            show_progress(msg)
            show_friendly_diff(lines, largest_lines, mail_file, largest_file)
            return 'diff'
        elif len(text_difference) == 0:
            if opts.show_diffs:
                show_progress("diff produced no differences")
        else:
            # Difference is inside threshold
            if opts.show_diffs:
                show_friendly_diff(lines, largest_lines, mail_file, largest_file)

    return False

def get_text_difference(lines, largest_lines):
    # We don't want the size of this diff to depend on the length of
    # the filenames or timestamps.
    diff = unified_diff(lines, largest_lines,
                        fromfile     = 'a', tofile     = 'b',
                        fromfiledate = '',  tofiledate = '',
                        n = 0, lineterm = "\n")
    difftext = "".join(diff)
    # print "".join(largest_lines[:20])
    # print "------\n"
    # print "".join(lines[:20])
    return difftext

def show_friendly_diff(from_lines, to_lines, from_file, to_file):
    friendly_diff = unified_diff(from_lines, to_lines,
                                 fromfile = 'body of ' + from_file,
                                 tofile   = 'body of ' + to_file,
                                 fromfiledate = os.path.getmtime(from_file),
                                 tofiledate = os.path.getmtime(to_file),
                                 n = 0, lineterm = "\n")
    show_progress("".join(friendly_diff))

def show_progress(msg):
    sys.stderr.write(msg + "\n")

def fatal(msg):
    show_progress(msg)
    sys.exit(1)

def main():
    opts, maildir_paths = parse_args()

    if opts.hash_pipe:
        debug_hash_algorithm(opts)
    else:
        duplicates_run(opts, maildir_paths)

def debug_hash_algorithm(opts):
    #mail_text = ''.join(sys.stdin.readlines())
    #message = email.message_from_string(mail_text)
    message = email.message_from_file(sys.stdin)
    mail_hash, header_text = compute_hash_key(message, opts.message_id)
    print header_text
    print 'Hash:', mail_hash

def duplicates_run(opts, maildir_paths):
    mails_by_hash = { }
    mail_count = 0

    check_maildirs_valid(maildir_paths)

    for maildir_path in maildir_paths:
        maildir = Maildir(maildir_path, factory = None)
        mail_count += collate_folder_by_hash(mails_by_hash, maildir, opts.message_id)

    duplicates, sizes_too_dissimilar, diff_too_big, removed, sets = \
        find_duplicates(mails_by_hash, opts)
    report_results(duplicates, sizes_too_dissimilar, diff_too_big,
                   removed, sets, mail_count)

def check_maildirs_valid(maildir_paths):
    for maildir_path in maildir_paths:
        if not os.path.exists(maildir_path):
            fatal("%s does not exist; aborting." % maildir_path)
        if not os.path.isdir(maildir_path):
            fatal("%s is not a directory; aborting." % maildir_path)
        for subdir in ('cur', 'new', 'tmp'):
            if not os.path.isdir(os.path.join(maildir_path, subdir)):
                fatal("%s is not a maildir (missing %s); aborting." %
                      (maildir_path, subdir))

def report_results(duplicates, sizes_too_dissimilar, diff_too_big,
                   removed, sets, mail_count):
    total = " in %d set%s from a total of %s mails." % \
        (sets, '' if sets == 1 else 's', mail_count)
    if removed > 0:
        results = 'Removed %d of %s duplicates found' % (removed, duplicates)
    else:
        results = 'Found %s duplicates' % duplicates

    show_progress("\n" + results + total)

    if sizes_too_dissimilar > 0:
        show_progress("%d potential duplicates were rejected as being "
                      "too dissimilar in size." % sizes_too_dissimilar)
    if diff_too_big > 0:
        show_progress("%d potential duplicates were rejected as being "
                      "too dissimilar in contents." % diff_too_big)

main()
