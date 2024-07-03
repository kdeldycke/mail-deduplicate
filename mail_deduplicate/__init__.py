# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
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
"""Expose package-wide elements."""

from __future__ import annotations

from pathlib import Path

from boltons.iterutils import unique

__version__ = "7.5.0"


HASH_HEADERS: tuple[str, ...] = (
    "Date",
    "From",
    "To",
    # 'Cc',
    # 'Bcc',
    # 'Reply-To',
    "Subject",
    "MIME-Version",
    "Content-Type",
    "Content-Disposition",
    "User-Agent",
    "X-Priority",
    "Message-ID",
)
"""Default ordered list of headers to use to compute the unique hash of a mail.

By default we choose to exclude:

``Cc``
  Since ``mailman`` apparently `sometimes trims list members
  <https://mail.python.org/pipermail/mailman-developers/2002-September/013233.html>`_
  from the ``Cc`` header to avoid sending duplicates. Which means that copies of mail
  reflected back from the list server will have a different ``Cc`` to the copy saved by
  the MUA at send-time.

``Bcc``
  Because copies of the mail saved by the MUA at send-time will have ``Bcc``, but copies
  reflected back from the list server won't.

``Reply-To``
  Since a mail could be ``Cc``'d to two lists with different ``Reply-To`` munging
  options set.
"""


MINIMAL_HEADERS_COUNT = 4
"""Below this value, we consider not having enough headers to compute a solid hash."""


DEFAULT_SIZE_THRESHOLD = 512
"""Default size threshold in bytes.

Since we're ignoring the ``Content-Length`` header by default `because of mailing-list
effects <https://kdeldycke.github.io/mail-deduplicate/design.html#mailing-lists>`_, we
introduced a limit on the allowed difference between the sizes of the message payloads.

If this is exceeded, a warning is issued and the messages are not considered duplicates,
because this could point to message corruption somewhere, or a false positive.

.. note::
    Headers are not counted towards this threshold, because many `headers can be added
    by mailing list software
    <https://kdeldycke.github.io/mail-deduplicate/design.html#mailing-lists>`_ such as
    ``mailman``, or even by the process of sending the mail through various MTAs.

    One copy could have been stored by the sender's MUA prior to sending, without any
    ``Received:`` headers, and another copy could be reflected back via a ``Cc``-to-self
    mechanism or mailing list server.

    This threshold has to be large enough to allow for footers added by mailing list
    servers.
"""

DEFAULT_CONTENT_THRESHOLD = 768
"""Default content threshold in bytes.

As above, we similarly generates unified diffs of duplicates and ensure that the diff is
not greater than a certain size to limit false-positives.
"""

DATE_HEADER = "date-header"
CTIME = "ctime"
TIME_SOURCES = frozenset([DATE_HEADER, CTIME])
"""Methods used to extract a mail's canonical timestamp:

- ``date-header``: sourced from the message's ``Date`` header.
- ``ctime``: sourced from the email's file from the filesystem. Only available for
  ``maildir`` sources.

Also see:
https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.mail.DedupMail.timestamp
"""


class TooFewHeaders(Exception):
    """Not enough headers were found to produce a solid hash."""


class SizeDiffAboveThreshold(Exception):
    """Difference in mail size is greater than `threshold.

    <https://kdeldycke.github.io/mail-
    deduplicate/mail_deduplicate.html#mail_deduplicate.DEFAULT_SIZE_THRESHOLD>`_.
    """


class ContentDiffAboveThreshold(Exception):
    """Difference in mail content is greater than `threshold.

    <https://kdeldycke.github.io/mail-
    deduplicate/mail_deduplicate.html#mail_deduplicate.DEFAULT_CONTENT_THRESHOLD>`_.
    """


class Config:
    """Holds global configuration."""

    # Keep these defaults in sync with CLI option definitions.
    default_conf = {
        "dry_run": False,
        "input_format": False,
        "force_unlock": False,
        "hash_headers": HASH_HEADERS,
        "hash_body": None,
        "hash_only": False,
        "size_threshold": DEFAULT_SIZE_THRESHOLD,
        "content_threshold": DEFAULT_CONTENT_THRESHOLD,
        "show_diff": False,
        "strategy": None,
        "time_source": None,
        "regexp": None,
        "action": None,
        "export": None,
        "export_format": "mbox",
        "export_append": False,
    }

    def __init__(self, **kwargs) -> None:
        """Validates configuration parameter types and values."""
        # Load default values.
        self.conf = self.default_conf.copy()

        unrecognized_options = set(kwargs) - set(self.default_conf)
        if unrecognized_options:
            msg = f"Unrecognized {unrecognized_options} options."
            raise ValueError(msg)

        # Replace defaults values with our config.
        self.conf.update(kwargs)

        # Check thresholds.
        assert self.size_threshold >= -1
        assert self.content_threshold >= -1

        # Headers are case-insensitive in Python implementation.
        normalized_headers = (h.lower() for h in self.hash_headers)  # type: ignore[has-type]
        # Remove duplicate entries.
        normalized_headers = unique(normalized_headers)
        # Mail headers are composed of ASCII characters between 33 and 126
        # (both inclusive) according the RFC-5322.
        for hid in normalized_headers:
            ascii_indexes = set(map(ord, hid))
            assert max(ascii_indexes) <= 126
            assert min(ascii_indexes) >= 33
        self.hash_headers = tuple(normalized_headers)

        # Export mail box will always be created from scratch and is not
        # expected to exists in the first place.
        if self.export:  # type: ignore[has-type]
            self.export = Path(self.export).resolve()  # type: ignore[has-type]
            if self.export.exists() and self.export_append is not True:
                raise FileExistsError(self.export)

    def __getattr__(self, attr_id):
        """Expose configuration entries as properties."""
        if attr_id in self.conf:
            return self.conf[attr_id]
        return None
