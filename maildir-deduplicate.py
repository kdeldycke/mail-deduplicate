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
    This script compare all mails in a maildir folder and subfolders,
    then delete duplicate mails.  You can give a list of mail headers
    to ignore when comparing mails between each others.  I used this
    script to clean up a messed maildir folder after I move several
    mails from a Lotus Notes database.

    Tested on MacOS X 10.6 with Python 2.6.2 and
    Linux with Python 2.6.0.
"""

import os
import re
import sys
import hashlib
import email
from optparse     import OptionParser
from mailbox      import Maildir
from email.parser import Parser
from difflib      import unified_diff

# List of mail headers to use when computing the hash of a mail.
#
# Note that we deliberately exclude certain headers due to the effects
# that mailing list software can have on not only the mail header but
# the body; it can potentially:
#
#   - append a footer to a list body, thus changing the
#     Content-Length header
#
#   - create a new path described by the Received headers which would
#     not be contained in any copy of the mail saved locally at
#     the time it was sent to the list
#
#   - munge the Reply-To header even though it's a bad idea
#
#   - add plenty of other random headers which a copy saved locally at
#     sending-time would not have, such as X-Mailman-Version,
#     Precedence, X-BeenThere, List-*, Sender, Errors-To, and so on.
#
#   - add a prefix to the Subject header
#
# Another difficulty is the lack of guarantee that Message-ID is
# unique or even present.  Yes, certain broken mail servers which
# must remain nameless are guilty of this :-(
HEADERS = [
    'Date',
    'From',
    'To',
    'Cc',
    'Bcc',
    'Subject',
    'Message-ID',
    'Reply-To',
    'MIME-Version',
    'Content-Type',
    'Content-Disposition',
    'User-Agent',
    'X-Priority',
]
HEADER_LOOKUP = dict((h.lower(), True) for h in HEADERS)

# Since we're ignoring the Content-Length header for the reasons
# stated above, we limit the allowed difference between message sizes.
# If this is exceeded, a warning is issued and the messages are not
# considered duplicates, because this could point to message
# corruption somewhere.  Note that the default is quite high because
# of the number of headers which can be added by mailman, or even by
# the process of sending the mail through various MTAs (since one copy
# could have been stored by the sender's MUA prior to sending).
DEFAULT_SIZE_DIFFERENCE_THRESHOLD = 2500 # bytes

# Similarly, we generated unified diffs of duplicates and ensure that
# the diff is not greater than a certain size.
DEFAULT_DIFF_THRESHOLD = 512 # bytes

def parse_args():
    parser = OptionParser(
        usage = '%prog [OPTIONS] [MAILDIR [MAILDIR ...]]',
        description = 'Detect/remove duplicates from maildir folders',
    )

    parser.add_option(
        '-d', '--remove', action = 'store_true',
        help = 'Remove duplicates rather than just list them'
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
               'of the whole header with selected headers removed'
    )
    parser.add_option(
        '-S', '--size-threshold', type = 'int',
        default = DEFAULT_SIZE_DIFFERENCE_THRESHOLD,
        help = 'Specify maximum allowed difference in bytes ' \
               'between size of duplicates. ' \
               'Default is %default; set -1 for no threshold.'
    )
    parser.add_option(
        '-D', '--diff-threshold', type = 'int',
        default = DEFAULT_DIFF_THRESHOLD,
        help = 'Specify maximum allowed size in bytes of unified diff ' \
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

    return opts, maildirs

def usage_error(parser, error_msg):
    sys.stderr.write("Error: %s\n\n" % error_msg)
    parser.print_help()
    sys.exit(2)

def canonise_mail(mail):
    # Delete all headers, then put back the ones we want in a fixed order.
    add_back = { }
    for header in mail.keys():
        if header.lower() in add_back:
            continue # already processed this one via get_all()
        if header.lower() in HEADER_LOOKUP:
            add_back[header.lower()] = (header, mail.get_all(header))
            #show_progress("  ignoring header '%s'" % header)
        del mail[header]

    for header in HEADERS:
        if header.lower() in add_back:
            header, values = add_back[header.lower()]
            for value in values:
                mail.add_header(header, value)

    # Trim Subject prefixes automatically added by mailing list software,
    # since the mail could have been cc'd to multiple lists, in which case
    # it will receive a different prefix for each, but this shouldn't be
    # treated as a real difference between duplicate mails.
    if mail['Subject']:
        m = re.match("(\[\w[\w_-]+\w\] )(.+)", mail['Subject'])
        if m:
            mail.replace_header('Subject', m.group(2))
            #show_progress("\nTrimmed '%s' from %s" % (m.group(1), mail['Subject']))

def compute_hash_key(message, use_message_id):
    header_text = get_header_text(message)

    if use_message_id:
        message_id = message.get('Message-Id')
        if message_id:
            return message_id
        sys.stderr.write("\n\nWARNING: no Message-ID in:\n" + header_text)
        #sys.exit(3)

    return hashlib.sha224(header_text).hexdigest(), header_text

def get_header_text(mail):
    #header_text, sep, payload = mail.as_string().partition("\n\n")
    header_text = ''.join('%s: %s\n' % (header, mail[header]) for header in HEADERS
                          if mail[header] is not None)
    return header_text

def collate_folder_by_hash(mails_by_hash, mail_folder, use_message_id):
    mail_count = 0
    path = re.sub(os.getenv('HOME'), '~', mail_folder._path)
    sys.stderr.write("Processing %s mails in %s " % \
                         (len(mail_folder), path))
    for mail_id, message in mail_folder.iteritems():
        canonise_mail(message)
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
    for hash_key, messages in mails_by_hash.iteritems():
        if len(messages) == 1:
            #print "unique:", messages[0]
            continue

        subject = messages[0][1].get('Subject')
        subject, count = re.subn('\s+', ' ', subject)
        print "\nSubject: " + subject

        sizes = sort_messages_by_size(messages)
        if not check_messages_similar(hash_key, sizes, opts):
            continue

        duplicates += len(messages) - 1
        sets += 1

        process_duplicates(sizes, opts)

    return duplicates, sets

def process_duplicates(sizes, opts):
    i = 0
    for size, mail_file, message in sizes:
        i += 1
        prefix = "  "
        if opts.remove:
            if i > 1:
                prefix = "removed"
                os.unlink(mail_file)
            else:
                prefix = "left   "
        print "%s %2d %d %s" % (prefix, i, size, mail_file)

def sort_messages_by_size(messages):
    sizes = [ ]
    for mail_file, message in messages:
        size = os.path.getsize(mail_file)
        sizes.append((size, mail_file, message))
    def _sort_by_size(a, b):
        return cmp(b[0], a[0])
    sizes.sort(cmp = _sort_by_size)
    return sizes

def get_lines_from_message(message):
    return message.as_string().splitlines(True)

def check_messages_similar(hash_key, sizes, opts):
    diff_threshold = opts.diff_threshold
    size_threshold = opts.size_threshold

    largest_size, largest_file, largest_message = sizes[0]
    largest_lines = get_lines_from_message(largest_message)

    for size, mail_file, message in sizes[1:]:
        size_difference = largest_size - size
        lines = get_lines_from_message(message)

        if size_threshold >= 0 and size_difference > size_threshold:
            msg = "For hash key %s, sizes differ by %d > %d bytes:\n" \
                  "  %d %s\n  %d %s" % \
                  (hash_key, size_difference, size_threshold,
                   size, mail_file,
                   largest_size, largest_file)
            show_progress(msg)
            # Showing the diff here can be misleading because the size
            # difference is often due to headers 

            #show_friendly_diff(lines, largest_lines, mail_file, largest_file)
            return False

        text_difference = get_text_difference(lines, largest_lines)
        if diff_threshold >= 0 and len(text_difference) > diff_threshold:
            msg = "diff between duplicate messages with hash key %s " \
                  "was %d > %d bytes\n" % \
                  (hash_key,
                   len(text_difference), diff_threshold)
            show_progress(msg)
            show_friendly_diff(lines, largest_lines, mail_file, largest_file)
            return False
        elif len(text_difference) == 0:
            if opts.show_diffs:
                show_progress("diff produced no differences")
        else:
            # Difference is inside threshold
            if opts.show_diffs:
                show_friendly_diff(lines, largest_lines, mail_file, largest_file)

    return True

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
                                 fromfile = 'canonical version of ' + from_file,
                                 tofile   = 'canonical version of ' + to_file,
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
    canonise_mail(message)
    mail_hash, header_text = compute_hash_key(message, opts.message_id)
    print header_text
    print 'Hash: ', mail_hash

def duplicates_run(opts, maildir_paths):
    mails_by_hash = { }
    mail_count = 0

    for maildir_path in maildir_paths:
        if not os.path.exists(maildir_path):
            fatal("%s does not exist; aborting." % maildir_path)
        if not os.path.isdir(maildir_path):
            fatal("%s is not a directory; aborting." % maildir_path)

        maildir = Maildir(maildir_path, factory = None)
        mail_count += collate_folder_by_hash(mails_by_hash, maildir, opts.message_id)

    duplicates, sets = find_duplicates(mails_by_hash, opts)
    show_progress("\n%s duplicates in %d sets from a total of %s mails." % \
                      (duplicates, sets, mail_count))

main()
