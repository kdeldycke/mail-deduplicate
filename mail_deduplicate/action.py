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

from typing import TYPE_CHECKING
import logging

from boltons.dictutils import FrozenDict
from boltons.iterutils import unique
from click_extra.colorize import default_theme as theme

from mail_deduplicate.mail_box import create_box

if TYPE_CHECKING:
    from .deduplicate import Deduplicate

COPY_SELECTED = "copy-selected"
COPY_DISCARDED = "copy-discarded"
MOVE_SELECTED = "move-selected"
MOVE_DISCARDED = "move-discarded"
DELETE_SELECTED = "delete-selected"
DELETE_DISCARDED = "delete-discarded"
"""Define all available action IDs."""


def copy_mails(dedup: Deduplicate, mails) -> None:
    """Copy provided ``mails`` to a brand new box or an existing one."""
    if not dedup.conf.dry_run:
        box = create_box(
            dedup.conf.export,
            dedup.conf.export_format,
            dedup.conf.export_append,
        )

    for mail in mails:
        logging.debug(f"Copying {mail!r} to {dedup.conf.export}...")
        dedup.stats["mail_copied"] += 1
        if dedup.conf.dry_run:
            logging.warning("DRY RUN: Skip action.")
        else:
            box.add(mail)
            logging.info(f"{mail!r} copied.")

    logging.debug(f"Close {dedup.conf.export}")
    if not dedup.conf.dry_run:
        box.close()


def move_mails(dedup: Deduplicate, mails) -> None:
    """Move provided ``mails`` to a brand new box or an existing one."""
    if not dedup.conf.dry_run:
        box = create_box(
            dedup.conf.export,
            dedup.conf.export_format,
            dedup.conf.export_append,
        )

    for mail in mails:
        logging.debug(
            f"Move {mail!r} form {mail.source_path} to {dedup.conf.export}..."
        )
        dedup.stats["mail_moved"] += 1
        if dedup.conf.dry_run:
            logging.warning("DRY RUN: Skip action.")
        else:
            box.add(mail)
            dedup.sources[mail.source_path].remove(mail.mail_id)
            logging.info(f"{mail!r} copied.")

    logging.debug(f"Close {dedup.conf.export}")
    if not dedup.conf.dry_run:
        box.close()


def delete_mails(dedup: Deduplicate, mails) -> None:
    """Remove provided ``mails`` in-place, from their original boxes."""
    for mail in mails:
        logging.debug(f"Deleting {mail!r} in-place...")
        dedup.stats["mail_deleted"] += 1
        if dedup.conf.dry_run:
            logging.warning("DRY RUN: Skip action.")
        else:
            dedup.sources[mail.source_path].remove(mail.mail_id)
            logging.info(f"{mail!r} deleted.")


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


ACTIONS = FrozenDict(
    {
        COPY_SELECTED: copy_selected,
        COPY_DISCARDED: copy_discarded,
        MOVE_SELECTED: move_selected,
        MOVE_DISCARDED: move_discarded,
        DELETE_SELECTED: delete_selected,
        DELETE_DISCARDED: delete_discarded,
    },
)
"""Map action ID's to their implementation."""


def perform_action(dedup: Deduplicate) -> None:
    """Performs the action on selected mail candidates."""
    logging.info(f"Perform {theme.choice(dedup.conf.action)} action...")

    selection_count = len(dedup.selection)
    if selection_count == 0:
        logging.warning("No mail selected to perform action on.")
        return
    logging.info(f"{selection_count} mails selected for action.")

    # Check our indexing and selection methods are not flagging candidates
    # several times.
    assert len(unique(dedup.selection)) == len(dedup.selection)
    assert len(dedup.selection) == dedup.stats["mail_selected"]

    # Hunt down for action implementation.
    method = ACTIONS.get(dedup.conf.action)
    if not method:
        msg = f"{dedup.conf.action} action not implemented yet."
        raise NotImplementedError(msg)

    method(dedup)
