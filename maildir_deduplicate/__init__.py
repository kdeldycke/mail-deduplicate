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

""" Expose package-wide elements. """


__version__ = '1.0.0'


# List of mail headers to use when computing the hash of a mail.
HEADERS = [
    'Date',
    'From',
    'To',

    # No Cc since mailman apparently sometimes trims list members from the Cc
    # header to avoid sending duplicates: http://mail.python.org/pipermail
    # /mailman-developers/2002-September/013233.html . But this means that
    # copies of mail reflected back from the list server will have a different
    # Cc to the copy saved by the MUA at send-time.
    # 'Cc',

    # No Bcc either since copies of the mail saved by the MUA at send-time
    # will have Bcc, but copies reflected back from the list server won't.
    # 'Bcc',

    # No Reply-To since a mail could be Cc'd to two lists with different
    # Reply-To munging options set.
    # 'Reply-To',

    'Subject',
    'Message-ID',
    'MIME-Version',
    'Content-Type',
    'Content-Disposition',
    'User-Agent',
    'X-Priority',
]


# Since we're ignoring the Content-Length header for the reasons stated above,
# we limit the allowed difference between the sizes of the message payloads. If
# this is exceeded, a warning is issued and the messages are not considered
# duplicates, because this could point to message corruption somewhere, or a
# false positive. Note that the headers are not counted towards this threshold,
# because many headers can be added by mailing list software such as mailman,
# or even by the process of sending the mail through various MTAs - one copy
# could have been stored by the sender's MUA prior to sending, without any
# Received: headers, and another copy could be reflected back via a Cc-to-self
# mechanism or mailing list server. But this threshold has to be at least large
# enough to allow for footers added by mailing list servers.
DEFAULT_SIZE_DIFFERENCE_THRESHOLD = 512  # bytes


# Similarly, we generated unified diffs of duplicates and ensure that the diff
# is not greater than a certain size.
DEFAULT_DIFF_THRESHOLD = 768  # bytes


# Use symbols to define removal strategies.
OLDER = 'older'
NEWER = 'newer'
SMALLER = 'smaller'
MATCHING = 'matching'
NOT_MATCHING = 'not-matching'
STRATEGIES = frozenset([OLDER, NEWER, SMALLER, MATCHING, NOT_MATCHING])


# Defines custom exception first to avoid circular imports.

class InsufficientHeadersError(Exception):

    """ Issue was encountered with email headers. """


# Expose important classes and methods to the root of the module. These are not
# lexicographically sorted to avoid cyclic imports.
from deduplicate import Deduplicate
