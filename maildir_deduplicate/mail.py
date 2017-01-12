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

import email
import hashlib
import os
import re
import textwrap
import time

from boltons.cacheutils import cachedproperty

from . import (
    CTIME,
    HEADERS,
    PY2,
    InsufficientHeadersError,
    MissingMessageID,
    logger
)


class Mail(object):

    """ Encapsulate a single mail and its metadata. """

    def __init__(self, path, conf):
        """ Build a mail from either a file. """
        # File path of the mail.
        self.path = path

        # Global config.
        self.conf = conf

    @cachedproperty
    def message(self):
        """ Read mail, parse it and return a Message instance. """
        logger.debug("Parsing mail at {} ...".format(self.path))
        with open(self.path, 'rb') as mail_file:
            if PY2:
                message = email.message_from_file(mail_file)
            else:
                message = email.message_from_binary_file(mail_file)
        return message

    @cachedproperty
    def timestamp(self):
        """ Compute the normalized canonical timestamp of the mail. """
        # XXX ctime does not refer to creation time on POSIX systems, but
        # rather the last time the inode data changed. Source:
        # https://userprimary.net/posts/2007/11/18
        # /ctime-in-unix-means-last-change-time-not-create-time/
        if self.conf.time_source == CTIME:
            return os.path.getctime(self.path)

        # Fetch from the date header.
        return email.utils.mktime_tz(email.utils.parsedate_tz(
            self.message.get('Date')))

    @cachedproperty
    def size(self):
        """ Returns canonical mail size.

        Size is computed as the lenght of the message body, i.e. the payload of
        the mail stripped of all its headers, not from the mail file
        persisting on the file-system.
        """
        return len(''.join(self.body_lines))

        # TODO: Allow customization of the way the size is computed, by getting
        # the file size instead for example.
        # size = os.path.getsize(mail_file)

    @cachedproperty
    def body_lines(self):
        """ Return a normalized list of lines from message's body. """
        if not self.message.is_multipart():
            body = self.message.get_payload(None, decode=True)
        else:
            _, _, body = self.message.as_string().partition("\n\n")
        if isinstance(body, bytes):
            for enc in ['ascii', 'utf-8']:
                try:
                    body = body.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                body = self.message.get_payload(None, decode=False)
        return body.splitlines(True)

    @cachedproperty
    def subject(self):
        """ Normalized subject.

        Only used for debugging and human-friendly logging.
        """
        # Fetch subject from first message.
        subject = self.message.get('Subject', '')
        subject, _ = re.subn(r'\s+', ' ', subject)
        return subject

    @cachedproperty
    def hash_key(self):
        """ Returns the canonical hash of a mail. """
        if self.conf.message_id:
            message_id = self.message.get('Message-Id')
            if message_id:
                return message_id.strip()
            logger.error(
                "No Message-ID in {}: {}".format(self.path, self.header_text))
            raise MissingMessageID

        return hashlib.sha224(self.canonical_headers).hexdigest()

    @cachedproperty
    def header_text(self):
        return ''.join(
            '{}: {}\n'.format(header, self.message[header])
            for header in HEADERS
            if self.message[header] is not None)

    @cachedproperty
    def canonical_headers(self):
        """ Copy selected headers into a new string. """
        canonical_headers = ''

        for header in HEADERS:
            if header not in self.message:
                continue

            for value in self.message.get_all(header):
                canonical_value = self.canonical_header_value(header, value)
                if re.search(r'\S', canonical_value):
                    canonical_headers += '{}: {}\n'.format(
                        header, canonical_value)

        canonical_headers = canonical_headers.encode('utf-8')
        if len(canonical_headers) > 50:
            return canonical_headers

        # At this point we should have at absolute minimum 3 or 4 headers, e.g.
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

    @staticmethod
    def canonical_header_value(header, value):
        header = header.lower()
        # Problematic when reading utf8 emails
        # this will ensure value is always string
        if not type(value) is str:
            value = value.encode()
        value = re.sub(r'\s+', ' ', value).strip()

        # Trim Subject prefixes automatically added by mailing list software,
        # since the mail could have been cc'd to multiple lists, in which case
        # it will receive a different prefix for each, but this shouldn't be
        # treated as a real difference between duplicate mails.
        if header == 'subject':
            subject = value
            while True:
                matching = re.match(
                    r"([Rr]e: )*(\[\w[\w_-]+\w\] )+(?s)(.+)", subject)
                if not matching:
                    break
                subject = matching.group(3)
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
