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
from __future__ import annotations

from mailbox import Maildir

from click_extra.pytest import skip_windows

from .conftest import MailFactory, check_box

""" Some invalid dates are not supported on Windows as they produce negative
timestamps. See:
* https://github.com/arrow-py/arrow/issues/675
* https://github.com/arrow-py/arrow/pull/745
"""

invalid_date_mail_1 = MailFactory(date_rfc2822="Thu, 13 Dec 101 15:30 WET")
invalid_date_mail_2 = MailFactory(date_rfc2822="Thu, 13 Dec 102 15:30 WET")


@skip_windows
def test_invalid_date_parsing_noop(invoke, make_box):
    """Mails with strange non-standard dates gets parsed anyway and grouped into
    duplicate sets.

    No deduplication happen: mails groups shares the same metadata.
    """
    box_path, box_type = make_box(
        Maildir,
        [
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )

    result = invoke("--strategy=select-newest", "--action=delete-selected", box_path)

    assert result.exit_code == 0

    check_box(
        box_path,
        box_type,
        content=[
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
        ],
    )


@skip_windows
def test_invalid_date_parsing_dedup(invoke, make_box):
    """Mails with strange non-standard dates gets parsed anyway and deduplicated if we
    reduce the source of hashed headers."""
    box_path, box_type = make_box(
        Maildir,
        [
            invalid_date_mail_1,
            invalid_date_mail_2,
            invalid_date_mail_2,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )

    result = invoke(
        "--hash-header=message-id",
        "--hash-header=from",
        "--hash-header=to",
        "--hash-header=subject",
        "--strategy=select-newest",
        "--action=delete-selected",
        box_path,
    )

    assert result.exit_code == 0

    check_box(
        box_path,
        box_type,
        content=[
            invalid_date_mail_1,
            invalid_date_mail_1,
            invalid_date_mail_1,
        ],
    )
