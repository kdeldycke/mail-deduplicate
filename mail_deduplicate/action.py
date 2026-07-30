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

import logging
import sys
from contextlib import contextmanager

from click_extra import OperationTrail, get_current_theme

from .deduplicate import Stat
from .mail_box import create_box

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .deduplicate import Deduplicate


@contextmanager
def export_box(dedup: Deduplicate) -> Iterator:
    """Context manager for export box operations."""
    if dedup.conf["dry_run"]:
        yield None
    else:
        assert dedup.conf["export"]
        box = create_box(
            dedup.conf["export"],
            dedup.conf["export_format"],
            dedup.conf["export_append"],
        )
        try:
            yield box
        finally:
            logging.debug(f"Close {dedup.conf['export']}")
            box.close()


def copy_mails(dedup: Deduplicate, mails) -> None:
    """Copy provided `mails` to a brand new box or an existing one."""
    trail = OperationTrail(label="Copying", unit="mails", total=len(mails))
    with export_box(dedup) as box:
        for mail in mails:
            logging.debug(f"Copying {mail!r} to {dedup.conf['export']}...")
            dedup.stats[Stat.MAIL_COPIED] += 1
            if dedup.conf["dry_run"]:
                logging.warning("DRY RUN: Skip action.")
            else:
                box.add(mail)
                trail.mark(True, f"{mail!r} copied")
    if not dedup.conf["dry_run"]:
        trail.finish(
            trail.ok_count == len(mails),
            f"Copied {trail.ok_count}/{len(mails)} mails",
        )


def move_mails(dedup: Deduplicate, mails) -> None:
    """Move provided `mails` to a brand new box or an existing one."""
    trail = OperationTrail(label="Moving", unit="mails", total=len(mails))
    with export_box(dedup) as box:
        for mail in mails:
            logging.debug(
                f"Move {mail!r} from {mail.source_path} to {dedup.conf['export']}..."
            )
            dedup.stats[Stat.MAIL_MOVED] += 1
            if dedup.conf["dry_run"]:
                logging.warning("DRY RUN: Skip action.")
            else:
                box.add(mail)
                dedup.sources[mail.source_path].remove(mail.mail_id)
                trail.mark(True, f"{mail!r} moved")
    if not dedup.conf["dry_run"]:
        trail.finish(
            trail.ok_count == len(mails),
            f"Moved {trail.ok_count}/{len(mails)} mails",
        )


def delete_mails(dedup: Deduplicate, mails) -> None:
    """Remove provided `mails` in-place, from their original boxes."""
    trail = OperationTrail(label="Deleting", unit="mails", total=len(mails))
    for mail in mails:
        logging.debug(f"Deleting {mail!r} in-place...")
        dedup.stats[Stat.MAIL_DELETED] += 1
        if dedup.conf["dry_run"]:
            logging.warning("DRY RUN: Skip action.")
        else:
            dedup.sources[mail.source_path].remove(mail.mail_id)
            trail.mark(True, f"{mail!r} deleted")
    if not dedup.conf["dry_run"]:
        trail.finish(
            trail.ok_count == len(mails),
            f"Deleted {trail.ok_count}/{len(mails)} mails",
        )


def copy_selected(dedup: Deduplicate) -> None:
    """Copy all selected mails to a brand new box."""
    copy_mails(dedup, dedup.selection)


def copy_discarded(dedup: Deduplicate) -> None:
    """Copy all discarded mails to a brand new box."""
    copy_mails(dedup, dedup.discard)


def move_selected(dedup: Deduplicate) -> None:
    """Move all selected mails to a brand new box."""
    move_mails(dedup, dedup.selection)


def move_discarded(dedup: Deduplicate) -> None:
    """Move all discarded mails to a brand new box."""
    move_mails(dedup, dedup.discard)


def delete_selected(dedup: Deduplicate) -> None:
    """Remove in-place all selected mails, from their original boxes."""
    delete_mails(dedup, dedup.selection)


def delete_discarded(dedup: Deduplicate) -> None:
    """Remove in-place all discarded mails, from their original boxes."""
    delete_mails(dedup, dedup.discard)


class Action(StrEnum):
    """Define all available action IDs."""

    COPY_SELECTED = "copy-selected"
    COPY_DISCARDED = "copy-discarded"
    MOVE_SELECTED = "move-selected"
    MOVE_DISCARDED = "move-discarded"
    DELETE_SELECTED = "delete-selected"
    DELETE_DISCARDED = "delete-discarded"

    @property
    def action_function(self) -> Callable:
        """Return the action function associated with this action."""
        func_name = self.name.lower()
        return globals()[func_name]  # type: ignore[no-any-return]

    def perform_action(self, dedup: Deduplicate) -> None:
        """Performs the action on selected mail candidates."""
        logging.info(f"Perform {get_current_theme().choice(str(self))} action...")

        selection_count = len(dedup.selection)
        if selection_count == 0:
            logging.warning("No mail selected to perform action on.")
            return
        logging.info(f"{selection_count} mails selected for action.")

        # Check the selection is consistent with the statistics gathered during
        # the selection phase.
        assert (
            len(dedup.selection)
            == dedup.stats[Stat.MAIL_SELECTED] + dedup.stats[Stat.MAIL_UNIQUE]
        )

        self.action_function(dedup)
