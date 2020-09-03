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
    InsufficientHeadersError,
    MissingMessageID,
    logger
)


class Mail(object):

    """ Encapsulate a single mail and its metadata. """

    def __init__(self, source_path, mail_id, conf):
        """ Create mail proxy pointing to its source path and unique ID. """
        # Path to the mail's source.
        self.source_path = source_path

        # Mail ID used to uniquely refers to it in the context of its source.
        self.mail_id = mail_id

        # Global config.
        self.conf = conf

    @cachedproperty
    def source(self):
        """ Return mail's source object. """
        # Import here to avoid circular imports.
        from .deduplicate import Deduplicate  # noqa
        return Deduplicate.sources[self.source_path]

    @cachedproperty
    def message(self):
        """ Fetch message from its source. """
        logger.debug("Fetching {!r} from {} ...".format(
            self.mail_id, self.source_path))
        return self.source.get_message(self.mail_id)

    @cachedproperty
    def path(self):
        """ Real filesystem path of the mail originating from maildirs.

        For mailbox mails, returns a fake path composed with mail's internal
        ID.
        """
        filename = self.message.get_filename()
        if filename:
            filepath = os.path.join(self.source_path, filename)
        else:
            filepath = ':'.join([self.source_path, self.mail_id])
        return filepath

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
        value = self.message.get('Date')
        try:
            value = email.utils.mktime_tz(email.utils.parsedate_tz(value))
        except ValueError:
            pass
        return value

        # XXX Also investigate what https://docs.python.org/2/library
        # /mailbox.html#mailbox.MaildirMessage.get_date does.

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
        body = []
        if self.message.preamble is not None:
            body.extend(self.message.preamble.splitlines(keepends=True))

        for part in self.message.walk():
            if part.is_multipart():
                continue

            ctype = part.get_content_type()
            cte = part.get_params(header='Content-Transfer-Encoding')
            if (ctype is not None and not ctype.startswith('text')) or \
               (cte is not None and cte[0][0].lower() == '8bit'):
                part_body = part.get_payload(decode=False)
            else:
                charset = part.get_content_charset()
                if charset is None or len(charset) == 0:
                    charsets = ['ascii', 'utf-8']
                else:
                    charsets = [charset]

                part_body = part.get_payload(decode=True)
                for enc in charsets:
                    try:
                        part_body = part_body.decode(enc)
                        break
                    except UnicodeDecodeError as ex:
                        continue
                    except LookupError as ex:
                        continue
                else:
                    part_body = part.get_payload(decode=False)

            body.extend(part_body.splitlines(keepends=True))

        if self.message.epilogue is not None:
            body.extend(self.message.epilogue.splitlines(keepends=True))
        return body

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
                "No Message-ID found: {}".format(self.header_text))
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
        if isinstance(value, bytes):
            value = value.decode('utf-8', 'replace')
        elif isinstance(value, email.header.Header):
            value = str(value)
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
                utc_timestamp = email.utils.mktime_tz(parsed)
                return time.strftime(
                    '%Y/%m/%d UTC', time.gmtime(utc_timestamp))
            except (TypeError, ValueError):
                return value
        elif header in ['to', 'message-id']:
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

    def delete(self):
        logger.debug("Deleting {!r}...".format(self))
        self.source.remove(self.mail_id)
        logger.info("{} deleted.".format(self.path))
