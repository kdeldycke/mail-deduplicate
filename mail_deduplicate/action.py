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

from boltons.iterutils import unique
from boltons.dictutils import FrozenDict

from . import logger
from .colorize import choice_style
from .mailbox import create_box


# Actions performed on the mail selection.
COPY_SELECTED = "copy-selected"
COPY_DISCARDED = "copy-discarded"
MOVE_SELECTED = "move-selected"
MOVE_DISCARDED = "move-discarded"
DELETE_SELECTED = "delete-selected"
DELETE_DISCARDED = "delete-discarded"


def copy_selected(dedup):
    """Copy all mails selected to a brand new box."""
    box = create_box(dedup.conf.export, dedup.conf.export_format)

    for mail in dedup.selection:
        logger.debug(f"Copying {mail!r} to {dedup.conf.export}...")
        dedup.stats["mail_copied"] += 1
        if dedup.conf.dry_run:
            logger.warning("DRY RUN: Skip action.")
        else:
            box.add(mail)
            logger.info(f"{mail!r} copied.")

    logger.debug(f"Close {dedup.conf.export}")
    box.close()


def move_selected(dedup):
    """Move all mails selected to a brand new box."""
    box = create_box(dedup.conf.export, dedup.conf.export_format)

    for mail in dedup.selection:
        logger.debug(f"Move {mail!r} form {mail.source_path} to {dedup.conf.export}...")
        dedup.stats["mail_moved"] += 1
        if dedup.conf.dry_run:
            logger.warning("DRY RUN: Skip action.")
        else:
            box.add(mail)
            dedup.sources[mail.source_path].remove(mail.mail_id)
            logger.info(f"{mail!r} copied.")

    logger.debug(f"Close {dedup.conf.export}")
    box.close()


def delete_selected(dedup):
    """Remove all mails selected in-place, from their original boxes."""
    for mail in dedup.selection:
        logger.debug(f"Deleting {mail!r} in-place...")
        dedup.stats["mail_deleted"] += 1
        if dedup.conf.dry_run:
            logger.warning("DRY RUN: Skip action.")
        else:
            dedup.sources[mail.source_path].remove(mail.mail_id)
            logger.info(f"{mail!r} deleted.")


ACTIONS = FrozenDict(
    {
        COPY_SELECTED: copy_selected,
        COPY_DISCARDED: None,
        MOVE_SELECTED: move_selected,
        MOVE_DISCARDED: None,
        DELETE_SELECTED: delete_selected,
        DELETE_DISCARDED: None,
    }
)


def perform_action(dedup):
    """Performs the action on selected mail candidates."""
    logger.info(f"Perform {choice_style(dedup.conf.action)} action...")

    selection_count = len(dedup.selection)
    if selection_count == 0:
        logger.warning("No mail selected to perform action on.")
        return
    logger.info(f"{selection_count} mails selected for action.")

    # Check our indexing and selection methods are not flagging candidates
    # several times.
    assert len(unique(dedup.selection)) == len(dedup.selection)
    assert len(dedup.selection) == dedup.stats["mail_selected"]

    # Hunt down for action implementation.
    method = ACTIONS.get(dedup.conf.action)
    if not method:
        raise NotImplementedError(f"{dedup.conf.action} action not implemented yet.")

    method(dedup)
