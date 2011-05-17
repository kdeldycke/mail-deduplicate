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
# of the number of headers mailman can add.
DEFAULT_SIZE_DIFFERENCE_THRESHOLD = 2048 # bytes

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
        '-s', '--show-diffs', action = 'store_true',
        help = 'Show diffs between duplicates'
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

    opts, maildirs = parser.parse_args()

    if len(maildirs) == 0:
        usage_error(parser, "Must specify at least one maildir folder")

    return opts, maildirs

def usage_error(parser, error_msg):
    sys.stderr.write("Error: %s\n\n" % error_msg)
    parser.print_help()
    sys.exit(2)

def computeHashKey(mail, use_message_id):
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

    if mail['Subject']:
        m = re.match("(\[\w[\w_-]+\w\] )(.+)", mail['Subject'])
        if m:
            mail.replace_header('Subject', m.group(2))
            #show_progress("\nTrimmed '%s' from %s" % (m.group(1), mail['Subject']))

    if use_message_id:
        message_id = mail.get('Message-Id')
        if message_id:
            return message_id
        sys.stderr.write("\n\nWARNING: no Message-ID in:\n" + getHeaderText(mail))
        #sys.exit(3)

    return hashlib.sha224(getHeaderText(mail)).hexdigest()

def getHeaderText(mail):
    #header_text, sep, payload = mail.as_string().partition("\n\n")
    header_text = ''.join('%s: %s\n' % (header, mail[header]) for header in HEADERS
                          if mail[header] is not None)
    return header_text

def collateFolderByHash(mails_by_hash, mail_folder, use_message_id):
    mail_count = 0
    path = re.sub(os.getenv('HOME'), '~', mail_folder._path)
    sys.stderr.write("Processing %s mails in %s " % \
                         (len(mail_folder), path))
    for mail_id, message in mail_folder.iteritems():
        mail_hash = computeHashKey(message, use_message_id)
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

def findDuplicates(mails_by_hash, opts):
    duplicates = 0
    sets = 0
    for hash_key, messages in mails_by_hash.iteritems():
        if len(messages) == 1:
            #print "unique:", messages[0]
            continue

        subject = messages[0][1].get('Subject')
        subject, count = re.subn('\s+', ' ', subject)
        print "\nSubject: " + subject

        sizes = sortMessagesBySize(messages)
        if not checkMessagesSimilar(hash_key, sizes, opts):
            continue
        if not checkSizesComparable(hash_key, sizes, opts.size_threshold):
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

def sortMessagesBySize(messages):
    sizes = [ ]
    for mail_file, message in messages:
        size = os.path.getsize(mail_file)
        sizes.append((size, mail_file, message))
    def _sort_by_size(a, b):
        return cmp(b[0], a[0])
    sizes.sort(cmp = _sort_by_size)
    return sizes

def checkSizesComparable(hash_key, sizes, threshold):
    if threshold < 0:
        return True

    largest_size, largest_file, largest_message = sizes[0]

    for size, mail_file, message in sizes[1:]:
        size_difference = largest_size - size
        if size_difference > threshold:
            msg = "\nFor hash key %s, sizes differ by %d > %d bytes:\n" \
                  "  %d %s\n  %d %s\n" % \
                  (hash_key, size_difference, threshold,
                   size, mail_file,
                   largest_size, largest_file)
            sys.stderr.write(msg)
            return False

    return True

def getLinesFromFile(path):
    f = open(path)
    lines = f.readlines()
    f.close()
    return lines

def checkMessagesSimilar(hash_key, sizes, opts):
    threshold = opts.diff_threshold
    if threshold < 0:
        return True

    largest_size, largest_file, largest_message = sizes[0]
    largest_lines = largest_message.as_string().splitlines(True)

    for size, mail_file, message in sizes[1:]:
        lines = message.as_string().splitlines(True)
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
        if opts.show_diffs or len(difftext) > threshold:
            friendly_diff = unified_diff(lines, largest_lines,
                                         fromfile = mail_file,
                                         tofile   = largest_file,
                                         fromfiledate = os.path.getmtime(mail_file),
                                         tofiledate = os.path.getmtime(largest_file),
                                         n = 0, lineterm = "\n")

        if len(difftext) > threshold:
            msg = "diff between duplicate messages with hash key %s " \
                  "was %d > %d bytes" % (hash_key, len(difftext), threshold)
            show_progress(msg)
            if opts.show_diffs:
                show_progress("".join(friendly_diff))
            return False
        elif len(difftext) == 0:
            if opts.show_diffs:
                show_progress("diff produced no differences")
        else:
            if opts.show_diffs:
                show_progress("".join(friendly_diff))

    return True

def show_progress(msg):
    sys.stderr.write(msg + "\n")

def main():
    opts, maildir_paths = parse_args()

    mails_by_hash = { }
    mail_count = 0

    for maildir_path in maildir_paths:
        maildir = Maildir(maildir_path, factory = None)
        mail_count += collateFolderByHash(mails_by_hash, maildir, opts.message_id)

    duplicates, sets = findDuplicates(mails_by_hash, opts)
    show_progress("\n%s duplicates in %d sets from a total of %s mails." % \
                      (duplicates, sets, mail_count))

main()
