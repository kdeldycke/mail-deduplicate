# -*- coding: utf-8 -*-
#
# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
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

import email
import hashlib
import os
import re
import textwrap
import time
import inspect
import mailbox

from tabulate import tabulate
from boltons.cacheutils import cachedproperty

from . import CTIME, TooFewHeaders, MINIMAL_HEADERS_COUNT, logger


class DedupMail:

    """Message with deduplication-specific properties and utilities.

    Adds all data-cleaning primitives and heuristics to Python's standard
    library messages from: https://github.com/python/cpython/blob
    /e799aa8b92c195735f379940acd9925961ad04ec/Lib/mailbox.py#L1489

    This class should not be used directly but composed with
    ``mailbox.Message`` sub-classes.
    """

    def __init__(self, message=None):
        """Initialize a pre-parsed ``Message`` instance the same way the default
        factory in Python's ``mailbox`` module does.
        """
        # Hunt down in our parent classes (but ourselve) the first one inheriting the
        # mailbox.Message class. That way we can get to the original factory.
        orig_message_klass = None
        for klass in inspect.getmro(self.__class__)[1:]:
            if issubclass(klass, mailbox.Message):
                orig_message_klass = klass
                break
        assert orig_message_klass

        # Call original object initialization from the right message class we
        # inherits from mailbox.Message.
        super(orig_message_klass, self).__init__(message)

        # Normalized path to the mailbox this message originates.
        self.source_path = None

        # Mail ID used to uniquely refers to it in the context of its source.
        self.mail_id = None

        # Global config.
        self.conf = None

    def __repr__(self):
        return "<Mail {!r}>".format(self.mail_id)

    @cachedproperty
    def path(self):
        """Real filesystem path of the mail originating from maildirs.

        For mailbox mails, returns a fake path composed with mail's internal
        ID.
        """
        filename = self.get_filename()
        if filename:
            filepath = self.source_path.joinpath(filename)
        else:
            filepath = "{}:{}".format(self.source_path, self.mail_id)
        return filepath

    @cachedproperty
    def timestamp(self):
        """Compute the normalized canonical timestamp of the mail.

        Sourced from the message's header by default. In the case of maildir,
        can be sourced from the email's file from the filesystem.
        """
        # XXX ctime does not refer to creation time on POSIX systems, but
        # rather the last time the inode data changed. Source:
        # https://userprimary.net/posts/2007/11/18
        # /ctime-in-unix-means-last-change-time-not-create-time/
        if self.conf.time_source == CTIME:
            return os.path.getctime(self.path)

        # Fetch from the date header.
        value = self.get("Date")
        try:
            value = email.utils.mktime_tz(email.utils.parsedate_tz(value))
        except ValueError:
            pass
        return value

        # XXX Also investigate what https://docs.python.org/2/library
        # /mailbox.html#mailbox.MaildirMessage.get_date does.

    @cachedproperty
    def size(self):
        """Returns canonical mail size.

        Size is computed as the length of the message body, i.e. the payload of
        the mail stripped of all its headers, not from the mail file
        persisting on the file-system.
        """
        return len("".join(self.body_lines))

        # TODO: Allow customization of the way the size is computed, by getting
        # the file size instead for example.
        # size = os.path.getsize(mail_file)

    @cachedproperty
    def body_lines(self):
        """ Return a normalized list of lines from message's body. """
        body = []
        if self.preamble is not None:
            body.extend(self.preamble.splitlines(keepends=True))

        for part in self.walk():
            if part.is_multipart():
                continue

            ctype = part.get_content_type()
            cte = part.get_params(header="Content-Transfer-Encoding")
            if (ctype is not None and not ctype.startswith("text")) or (
                cte is not None and cte[0][0].lower() == "8bit"
            ):
                part_body = part.get_payload(decode=False)
            else:
                charset = part.get_content_charset()
                if charset is None or len(charset) == 0:
                    charsets = ["ascii", "utf-8"]
                else:
                    charsets = [charset]

                part_body = part.get_payload(decode=True)
                for enc in charsets:
                    try:
                        part_body = part_body.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                    except LookupError:
                        continue
                else:
                    part_body = part.get_payload(decode=False)

            body.extend(part_body.splitlines(keepends=True))

        if self.epilogue is not None:
            body.extend(self.epilogue.splitlines(keepends=True))
        return body

    @cachedproperty
    def subject(self):
        """Normalized subject.

        Only used for debugging and human-friendly logging.
        """
        # Fetch subject from first message.
        subject = self.get("Subject", "")
        subject, _ = re.subn(r"\s+", " ", subject)
        return subject

    @cachedproperty
    def hash_key(self):
        """ Returns the canonical hash of a mail. """
        logger.debug(f"Serialized headers: {self.serialized_headers!r}")
        hash_value = hashlib.sha224(self.serialized_headers).hexdigest()
        logger.debug(f"Hash: {hash_value}")
        return hash_value

    @cachedproperty
    def canonical_headers(self):
        """Returns the full list of all canonical headers names and values in preparation for hashing."""
        canonical_headers = []

        for header_id in self.conf.hash_headers:

            # Skip absent header.
            if header_id not in self:
                continue

            # Fetch all occurrences of the header.
            canonical_values = []
            for header_value in self.get_all(header_id):
                normalized_value = self.normalize_header_value(header_id, header_value)
                if re.search(r"\S", normalized_value):
                    canonical_values.append(normalized_value)
            canonical_value = "\n".join(canonical_values)

            canonical_headers.append((header_id, canonical_value))

        # Cast to a tuple to prevent any modification.
        return tuple(canonical_headers)

    @cachedproperty
    def pretty_canonical_headers(self):
        """Renders into a table and in the same order, headers names and values
        used to produce mail's hash.

        Returns a string ready to be printing to user or for debugging.
        """
        table = [["Header ID", "Header value"]] + list(self.canonical_headers)
        return tabulate(table, tablefmt="fancy_grid", headers="firstrow")

    @cachedproperty
    def serialized_headers(self):
        """ Serialize the canonical headers into a single string ready to be hashed. """
        # At this point we should have at an absolute minimum of headers.
        headers_count = len(self.canonical_headers)
        if headers_count < MINIMAL_HEADERS_COUNT:
            logger.warning(self.pretty_canonical_headers)
            raise TooFewHeaders(
                f"{headers_count} headers found out of {MINIMAL_HEADERS_COUNT}."
            )
        else:
            logger.debug(self.pretty_canonical_headers)

        return "\n".join(
            ["{}: {}".format(h_id, h_value) for h_id, h_value in self.canonical_headers]
        ).encode("utf-8")

    @staticmethod
    def normalize_header_value(header_id, value):
        """Normalize and clean-up header value into its canonical form.

        Always returns a unicode string.
        """
        # Problematic when reading utf8 emails
        # this will ensure value is always string
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        elif isinstance(value, email.header.Header):
            value = str(value)

        # Normalize white spaces.
        value = re.sub(r"\s+", " ", value).strip()

        # Trim Subject prefixes automatically added by mailing list software,
        # since the mail could have been cc'd to multiple lists, in which case
        # it will receive a different prefix for each, but this shouldn't be
        # treated as a real difference between duplicate mails.
        if header_id == "subject":
            subject = value
            while True:
                matching = re.match(
                    r"([Rr]e: )*(\[\w[\w_-]+\w\] )+(.+)", subject, re.DOTALL
                )
                if not matching:
                    break
                subject = matching.group(3)
                # show_progress("Trimmed Subject to %s" % subject)
            return subject

        if header_id == "content-type":
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
            return re.sub(";.*", "", value)

        if header_id == "date":
            # Date timestamps can differ by seconds or hours for various
            # reasons, so let's only honour the date for now and normalize them
            # to UTC timezone.
            try:
                parsed = email.utils.parsedate_tz(value)
                if not parsed:
                    raise TypeError
                utc_timestamp = email.utils.mktime_tz(parsed)
                return time.strftime("%Y-%m-%d", time.gmtime(utc_timestamp))
            except (TypeError, ValueError):
                return value

        elif header_id in ["to", "message-id"]:
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
