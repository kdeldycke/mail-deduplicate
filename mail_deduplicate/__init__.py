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

""" Expose package-wide elements. """

import logging
import sys

__version__ = '3.0.1'


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3


logger = logging.getLogger(__name__)


# List of mail headers to use when computing the hash of a mail.
HEADERS = [
    'Date',
    'From',
    'To',

    # No Cc since mailman apparently sometimes trims list members from the Cc
    # header to avoid sending duplicates: https://mail.python.org/pipermail
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
    'MIME-Version',
    'Content-Type',
    'Content-Disposition',
    'User-Agent',
    'X-Priority',
    'Message-ID',
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
DEFAULT_SIZE_THRESHOLD = 512  # bytes


# Similarly, we generated unified diffs of duplicates and ensure that the diff
# is not greater than a certain size.
DEFAULT_CONTENT_THRESHOLD = 768  # bytes


# Use symbols to define removal strategies.
DELETE_OLDER = 'delete-older'
DELETE_OLDEST = 'delete-oldest'
DELETE_NEWER = 'delete-newer'
DELETE_NEWEST = 'delete-newest'

DELETE_SMALLER = 'delete-smaller'
DELETE_SMALLEST = 'delete-smallest'
DELETE_BIGGER = 'delete-bigger'
DELETE_BIGGEST = 'delete-biggest'

DELETE_MATCHING_PATH = 'delete-matching-path'
DELETE_NON_MATCHING_PATH = 'delete-non-matching-path'

STRATEGIES = frozenset([
    DELETE_OLDER, DELETE_OLDEST,
    DELETE_NEWER, DELETE_NEWEST,
    DELETE_SMALLER, DELETE_SMALLEST,
    DELETE_BIGGER, DELETE_BIGGEST,
    DELETE_MATCHING_PATH, DELETE_NON_MATCHING_PATH])


# Sources from which we compute a mail's canonical timestamp.
DATE_HEADER = 'date-header'
CTIME = 'ctime'
TIME_SOURCES = frozenset([DATE_HEADER, CTIME])


# List of required sub-folders defining a properly structured maildir.
MD_SUBDIRS = frozenset(('cur', 'new', 'tmp'))


# Defines custom exception first to avoid circular imports.

class InsufficientHeadersError(Exception):

    """ Issue was encountered with email headers. """


class MissingMessageID(Exception):

    """ No Message-ID header found in email headers. """


class SizeDiffAboveThreshold(Exception):

    """ Difference in mail size is greater than threshold. """


class ContentDiffAboveThreshold(Exception):

    """ Difference in mail content is greater than threshold. """


class Config(object):

    """ Holds global configuration. """

    # Keep these defaults in sync with CLI option definitions.
    default_conf = {
        'strategy': None,
        'time_source': None,
        'regexp': None,
        'dry_run': False,
        'show_diff': False,
        'message_id': False,
        'size_threshold': DEFAULT_SIZE_THRESHOLD,
        'content_threshold': DEFAULT_CONTENT_THRESHOLD,
        'progress': True,
    }

    def __init__(self, **kwargs):
        # Load default values.
        self.conf = self.default_conf.copy()

        for param, value in kwargs.items():
            if param not in self.default_conf:
                raise ValueError(
                    "Unrecognized {} configuration option.".format(param))
            self.conf[param] = value

        # Validates configuration.
        assert self.size_threshold >= -1
        assert self.content_threshold >= -1

    def __getattr__(self, attr_id):
        """ Expose configuration entries as properties. """
        if attr_id in self.conf:
            return self.conf[attr_id]
        return super(Config, self).__getattr__(attr_id)
