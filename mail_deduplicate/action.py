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

import filecmp
import logging
import os
import sys
from collections import Counter
from contextlib import contextmanager
from uuid import uuid4

from click_extra import OperationTrail, format_size, get_current_theme

from .deduplicate import Stat
from .mail_box import FOLDER_FORMAT_CLASSES, create_box

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

    from .deduplicate import Deduplicate
    from .mail import DedupMailMixin


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


def dry_run_prefix(dedup: Deduplicate) -> str:
    """Marks a summary as describing what a run would have done.

    A dry run reports through the same trail as a real one, so what it did not do is
    said once at the end rather than warned about for every single mail.
    """
    return "DRY RUN: would have " if dedup.conf["dry_run"] else ""


def copy_mails(dedup: Deduplicate, mails) -> None:
    """Copy provided `mails` to a brand new box or an existing one."""
    trail = OperationTrail(label="Copying", unit="mails", total=len(mails))
    with export_box(dedup) as box:
        for mail in mails:
            logging.debug(f"Copying {mail!r} to {dedup.conf['export']}...")
            dedup.stats[Stat.MAIL_COPIED] += 1
            if not dedup.conf["dry_run"]:
                with mail.hydrated():
                    box.add(mail)
            trail.mark(True, f"{mail!r} copied")
    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Copied {trail.ok_count}/{len(mails)} mails",
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
            if not dedup.conf["dry_run"]:
                with mail.hydrated():
                    box.add(mail)
                dedup.sources[mail.source_path].remove(mail.mail_id)
            trail.mark(True, f"{mail!r} moved")
    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Moved {trail.ok_count}/{len(mails)} mails",
    )


def delete_mails(dedup: Deduplicate, mails) -> None:
    """Remove provided `mails` in-place, from their original boxes."""
    trail = OperationTrail(label="Deleting", unit="mails", total=len(mails))
    for mail in mails:
        logging.debug(f"Deleting {mail!r} in-place...")
        dedup.stats[Stat.MAIL_DELETED] += 1
        if not dedup.conf["dry_run"]:
            dedup.sources[mail.source_path].remove(mail.mail_id)
        trail.mark(True, f"{mail!r} deleted")
    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Deleted {trail.ok_count}/{len(mails)} mails",
    )


LINK_TEMP_PREFIX = ".mdedup-hardlink-"
"""Prefix of the temporary link a mail is replaced through.

Every folder-based format skips dot-prefixed files when listing its mails, so a
temporary left behind by an interrupted run is never read back as one.
"""


FOLDER_BOX_CLASSES = tuple(FOLDER_FORMAT_CLASSES)
"""Box classes giving each of their mails a file of its own, ready for `isinstance`."""


def has_own_file(mail: DedupMailMixin) -> bool:
    """Whether the mail is backed by a file holding it alone.

    File-based boxes pack all their mails into the box's single file, which is what
    `path` returns for each of them: there would be nothing to link but the whole box.
    """
    return isinstance(mail.box, FOLDER_BOX_CLASSES)


def hardlink_blocker(
    dedup: Deduplicate, mail: DedupMailMixin, target: DedupMailMixin
) -> str | None:
    """Explain why a mail cannot be replaced by a hardlink to its target.

    Returns the reason as a sentence ready to be logged, or `None` when the link can
    go ahead. Nothing is touched along the way, so a dry run reaches the same verdicts
    a real run acts on.
    """
    if not has_own_file(mail) or not has_own_file(target):
        return "mails of a file-based box have no file of their own to link"

    try:
        mail_stat = os.stat(mail.path)
        target_stat = os.stat(target.path)
    except OSError as expt:
        return f"the mail or its copy cannot be read back ({expt.strerror})"

    if (mail_stat.st_dev, mail_stat.st_ino) == (
        target_stat.st_dev,
        target_stat.st_ino,
    ):
        return "the mail already shares the file of the copy kept"

    if mail_stat.st_dev != target_stat.st_dev:
        return "the mail and the copy kept live on different filesystems"

    if not dedup.conf["hardlink_differing"] and not filecmp.cmp(
        mail.path, target.path, shallow=False
    ):
        return (
            "the mail differs byte for byte from the copy kept, so linking it would "
            "swap its own content for that copy's (--hardlink-differing links them "
            "anyway)"
        )

    return None


def replace_by_hardlink(mail_path: str, target_path: str) -> None:
    """Point a mail's own path at the file backing another mail.

    The link is created under a temporary name in the mail's own directory, then
    renamed over it: the rename is atomic and shares the mail's filesystem by
    construction, so the mail is never missing from its box, whatever interrupts the
    run. The mail also keeps its file name, which is where `maildir` records the
    per-folder flags that make the same mail read in one folder and unread in another.
    """
    temp_path = os.path.join(
        os.path.dirname(mail_path), f"{LINK_TEMP_PREFIX}{uuid4().hex}"
    )
    os.link(target_path, temp_path)
    try:
        os.replace(temp_path, mail_path)
    except OSError:
        os.unlink(temp_path)
        raise


def hardlink_mails(dedup: Deduplicate, mails: Collection[DedupMailMixin]) -> None:
    """Replace provided `mails` in-place by a hardlink to the copy kept in their set.

    The mails stay right where they are, under their own name: only the content they
    are backed by is shared with the copy that survived the selection, so the disk
    space they took is reclaimed.
    """
    reclaimed = 0
    # Why mails were passed over is said once per reason at the end, rather than once
    # per mail: a corpus can hand over as many skipped mails as it has duplicates.
    skipped: Counter[str] = Counter()
    trail = OperationTrail(label="Hardlinking", unit="mails", total=len(mails))

    for mail in mails:
        target = dedup.link_targets[mail]

        blocker = hardlink_blocker(dedup, mail, target)
        freed = 0
        if not blocker:
            try:
                # Measured while the mail is still backed by a file of its own: this
                # is the space it stops taking once it shares the copy's.
                freed = os.path.getsize(mail.path)
                if not dedup.conf["dry_run"]:
                    replace_by_hardlink(mail.path, target.path)
            except OSError as expt:
                # Reported by its error string alone: the paths that come with the
                # exception are unique to each mail, and would leave every failure
                # to be logged on a line of its own.
                blocker = f"the link could not be created ({expt.strerror})"

        if blocker:
            logging.debug(f"Skip {mail!r}: {blocker}.")
            skipped[blocker] += 1
            dedup.stats[Stat.MAIL_HARDLINK_SKIPPED] += 1
            trail.mark(False, f"{mail!r} skipped")
            continue

        logging.debug(f"Hardlinked {mail!r} to {target!r}.")
        reclaimed += freed
        dedup.stats[Stat.MAIL_HARDLINKED] += 1
        trail.mark(True, f"{mail!r} hardlinked")

    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Hardlinked {trail.ok_count}/{len(mails)} mails, "
        f"reclaiming {format_size(reclaimed)}",
    )

    for reason, count in skipped.most_common():
        logging.warning(f"{count} mails left untouched: {reason}.")


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


def hardlink_discarded(dedup: Deduplicate) -> None:
    """Replace in-place all discarded mails by a hardlink to the copy kept."""
    hardlink_mails(dedup, dedup.discard)


class Action(StrEnum):
    """Define all available action IDs."""

    COPY_SELECTED = "copy-selected"
    COPY_DISCARDED = "copy-discarded"
    MOVE_SELECTED = "move-selected"
    MOVE_DISCARDED = "move-discarded"
    DELETE_SELECTED = "delete-selected"
    DELETE_DISCARDED = "delete-discarded"
    HARDLINK_DISCARDED = "hardlink-discarded"

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

        if dedup.conf["dry_run"]:
            # Said once, and loudly. The statistics below count what the action
            # would have touched, so without this line a dry run reads exactly like
            # a real one. The trail's own summary cannot carry the warning alone:
            # it only shows on an interactive terminal.
            #
            # Counted off the subset this action targets, which is the discarded
            # mails for the *-discarded half of them, not the selected ones.
            targets = (
                dedup.discard if str(self).endswith("-discarded") else dedup.selection
            )
            logging.warning(
                f"DRY RUN: {len(targets)} mails would be acted upon, "
                "but none will be altered.",
            )

        # Check the selection is consistent with the statistics gathered during
        # the selection phase.
        assert (
            len(dedup.selection)
            == dedup.stats[Stat.MAIL_SELECTED] + dedup.stats[Stat.MAIL_UNIQUE]
        )

        self.action_function(dedup)
