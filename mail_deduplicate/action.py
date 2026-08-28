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
"""Actions performed once the selection is settled: copy, move, delete or hardlink.

Each action ID pairs an operation verb with the subset of mails it applies to, and
`Action.perform()` routes one to the other.
"""

from __future__ import annotations

import filecmp
import logging
import os
from collections import Counter
from contextlib import contextmanager
from typing import cast
from uuid import uuid4

from click_extra import OperationTrail, format_size, get_current_theme

from . import StrEnum
from .deduplicate import Stat
from .mail_box import FOLDER_FORMAT_CLASSES, create_box

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator
    from mailbox import Mailbox

    from .deduplicate import Deduplicate
    from .mail import DedupMailMixin


@contextmanager
def export_box(dedup: Deduplicate) -> Iterator[Mailbox | None]:
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


def copy_mails(dedup: Deduplicate, mails: Collection[DedupMailMixin]) -> None:
    """Copy provided `mails` to a brand new box or an existing one."""
    trail = OperationTrail(label="Copying", unit="mails", total=len(mails))
    with export_box(dedup) as box:
        for mail in mails:
            logging.debug(f"Copying {mail!r} to {dedup.conf['export']}...")
            dedup.stats[Stat.MAIL_COPIED] += 1
            if not dedup.conf["dry_run"]:
                # The box is only left closed on a dry run, ruled out just above.
                assert box is not None
                with mail.hydrated():
                    box.add(mail)
            trail.mark(True, f"{mail!r} copied")
    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Copied {trail.ok_count}/{len(mails)} mails",
    )


def move_mails(dedup: Deduplicate, mails: Collection[DedupMailMixin]) -> None:
    """Move provided `mails` to a brand new box or an existing one."""
    trail = OperationTrail(label="Moving", unit="mails", total=len(mails))
    with export_box(dedup) as box:
        for mail in mails:
            logging.debug(
                f"Move {mail!r} from {mail.source_path} to {dedup.conf['export']}..."
            )
            dedup.stats[Stat.MAIL_MOVED] += 1
            if not dedup.conf["dry_run"]:
                # The box is only left closed on a dry run, ruled out just above.
                assert box is not None
                with mail.hydrated():
                    box.add(mail)
                # Identity attributes are set the moment a mail is read from its
                # box, which every mail reaching an action has been.
                dedup.sources[cast("str", mail.source_path)].remove(
                    cast("str", mail.mail_id)
                )
            trail.mark(True, f"{mail!r} moved")
    trail.finish(
        trail.ok_count == len(mails),
        f"{dry_run_prefix(dedup)}Moved {trail.ok_count}/{len(mails)} mails",
    )


def delete_mails(dedup: Deduplicate, mails: Collection[DedupMailMixin]) -> None:
    """Remove provided `mails` in-place, from their original boxes."""
    trail = OperationTrail(label="Deleting", unit="mails", total=len(mails))
    for mail in mails:
        logging.debug(f"Deleting {mail!r} in-place...")
        dedup.stats[Stat.MAIL_DELETED] += 1
        if not dedup.conf["dry_run"]:
            # Identity attributes are set the moment a mail is read from its box,
            # which every mail reaching an action has been.
            dedup.sources[cast("str", mail.source_path)].remove(
                cast("str", mail.mail_id)
            )
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


def has_own_file(mail: DedupMailMixin) -> bool:
    """Whether the mail is backed by a file holding it alone.

    File-based boxes pack all their mails into the box's single file, which is what
    `path` returns for each of them: there would be nothing to link but the whole box.
    """
    return isinstance(mail.box, FOLDER_FORMAT_CLASSES)


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


OPERATIONS: dict[str, Callable[[Deduplicate, Collection[DedupMailMixin]], None]] = {
    "copy": copy_mails,
    "move": move_mails,
    "delete": delete_mails,
    "hardlink": hardlink_mails,
}
"""The operation functions above, keyed by the verb half of an action ID.

All share the same signature: the deduplication they report to, and the mails they
apply to.
"""


class Action(StrEnum):
    """Define all available action IDs.

    An action ID joins an operation verb to the subset of mails it applies to: the
    `*-selected` actions act on the mails kept by the selection, the `*-discarded`
    ones on the mails it discarded.

    The mails that have no duplicate belong to the selection, so the copy and move
    actions carry them into the box they build. `spares_unique` explains why the
    delete one leaves them behind.
    """

    COPY_SELECTED = "copy-selected"
    COPY_DISCARDED = "copy-discarded"
    MOVE_SELECTED = "move-selected"
    MOVE_DISCARDED = "move-discarded"
    DELETE_SELECTED = "delete-selected"
    DELETE_DISCARDED = "delete-discarded"
    HARDLINK_DISCARDED = "hardlink-discarded"

    @property
    def verb(self) -> str:
        """The operation half of the action ID, keying into `OPERATIONS`."""
        return self.value.partition("-")[0]

    @property
    def acts_on_discarded(self) -> bool:
        """Whether the action applies to the discarded mails rather than the selected
        ones."""
        return self.value.endswith("-discarded")

    @property
    def spares_unique(self) -> bool:
        """Whether the action must leave the mails that have no duplicate alone.

        A mail alone in its duplicate set is kept, so it belongs to the selection
        every `*-selected` action targets. Copying and moving it is what makes the
        exported box hold the whole deduplicated corpus rather than its duplicates
        only, and neither loses it. Deleting it does: no strategy ever ruled on that
        mail, nothing was written anywhere else, and there is no other copy of it to
        fall back on. So the deletion applies to the mails a strategy really picked.
        See: https://github.com/kdeldycke/mail-deduplicate/issues/1053
        """
        return self is Action.DELETE_SELECTED

    def targets(self, dedup: Deduplicate) -> set[DedupMailMixin]:
        """The subset of mails this action applies to."""
        if self.acts_on_discarded:
            return dedup.discard
        if self.spares_unique:
            return dedup.selection - dedup.unique
        return dedup.selection

    def perform(self, dedup: Deduplicate) -> None:
        """Perform the action on the subset of mails it targets."""
        logging.info(f"Perform {get_current_theme().choice(str(self))} action...")

        selection_count = len(dedup.selection)
        if selection_count == 0:
            logging.warning("No mail selected to perform action on.")
            return
        logging.info(f"{selection_count} mails selected for action.")

        targets = self.targets(dedup)
        if self.spares_unique and dedup.unique:
            # Said before the count below, which it accounts for.
            logging.warning(
                f"{len(dedup.unique)} mails left untouched: they have no duplicate, "
                "so deleting them would leave no copy behind.",
            )

        if dedup.conf["dry_run"]:
            # Said once, and loudly. The statistics below count what the action
            # would have touched, so without this line a dry run reads exactly like
            # a real one. The trail's own summary cannot carry the warning alone:
            # it only shows on an interactive terminal.
            logging.warning(
                f"DRY RUN: {len(targets)} mails would be acted upon, "
                "but none will be altered.",
            )

        # Check the selection is consistent with the statistics gathered during
        # the selection phase.
        assert (
            selection_count
            == dedup.stats[Stat.MAIL_SELECTED] + dedup.stats[Stat.MAIL_UNIQUE]
        )

        OPERATIONS[self.verb](dedup, targets)
