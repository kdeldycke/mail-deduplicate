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
"""Utilities to read and write mail boxes in various formats.

Based on `Python's standard library mailbox module
<https://docs.python.org/3.11/library/mailbox.html>`_.
"""

from __future__ import annotations

import logging
import mailbox
from enum import Enum, auto
from functools import partial
from mailbox import MH, MMDF, Babyl, ExternalClashError, Mailbox, Maildir, mbox

from click_extra.colorize import default_theme as theme

from .mail import DedupMailMixin


def make_dedup_mail(name: str, base: type) -> type:
    """Create a DedupMail class for a mailbox message type."""
    return type(name, (DedupMailMixin, base), {})


MaildirDedupMail = make_dedup_mail("MaildirDedupMail", mailbox.MaildirMessage)
mboxDedupMail = make_dedup_mail("mboxDedupMail", mailbox.mboxMessage)
MHDedupMail = make_dedup_mail("MHDedupMail", mailbox.MHMessage)
BabylDedupMail = make_dedup_mail("BabylDedupMail", mailbox.BabylMessage)
MMDFDedupMail = make_dedup_mail("MMDFDedupMail", mailbox.MMDFMessage)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from pathlib import Path


class BoxStructure(Enum):
    """Box structures can be file-based or folder-based."""

    # We use auto() as we don't care about the actual values here.
    FOLDER = auto()
    FILE = auto()


class BoxFormat(Enum):
    """IDs of all the supported box formats and their metadata.

    Each entry is associated to:

    - their original base class,
    - the structure they implement (file-based or folder-based),
    - the custom message factory class to use.

    From these, we can derive the proper constructor with our own custom ``DedupMail``
    factory.

    .. hint::
        This could be extended in the future to add support for other mailbox formats
        and sources, like Gmail accounts, IMAP servers, etc.
    """

    # Same order as in `mailbox` module documentation.
    MAILDIR = (Maildir, BoxStructure.FOLDER, MaildirDedupMail)
    MBOX = (mbox, BoxStructure.FILE, mboxDedupMail)
    MH = (MH, BoxStructure.FOLDER, MHDedupMail)
    BABYL = (Babyl, BoxStructure.FILE, BabylDedupMail)
    MMDF = (MMDF, BoxStructure.FILE, MMDFDedupMail)

    def __init__(
        self,
        base_class: type[Mailbox],
        structure: BoxStructure,
        message_class: type[DedupMailMixin],
    ) -> None:
        self.base_class = base_class
        self.structure = structure
        self.message_class = message_class

    def __str__(self):
        """The lowercase name of the format is used as a key in CLI options."""
        return self.name.lower()

    @property
    def constructor(self):
        """Return a constructor for this box format with our custom message factory."""
        return partial(self.base_class, factory=self.message_class)


FOLDER_FORMATS = tuple(box for box in BoxFormat if box.structure == BoxStructure.FOLDER)
"""Box formats implementing a folder-based structure.

Is a tuple to keep natural order defined by ``BoxFormat``.
"""


FILE_FORMATS = tuple(box for box in BoxFormat if box.structure == BoxStructure.FILE)
"""Box formats implementing a file-based structure.

Is a tuple to keep natural order defined by ``BoxFormat``.
"""


MAILDIR_SUBDIRS = frozenset(("cur", "new", "tmp"))
"""List of required sub-folders defining a properly structured maildir."""


def autodetect_box_type(path: Path) -> BoxFormat:
    """Auto-detect the format of the mailbox located at the provided path.

    Returns a box type as indexed in the `BOX_TYPES
    <https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.mailbox.BOX_TYPES>`_
    dictionary above.

    If the path is a file, then it is considered as an ``mbox``. Else, if the
    provided path is a folder and feature the `expecteed sub-directories
    <https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.mailbox.MAILDIR_SUBDIRS>`_,
    it is parsed as a ``maildir``.

    .. todo::
        Future finer autodetection heuristics should be implemented here. Some ideas:

        - single mail from a ``maildir``
        - plain text mail content
        - other mailbox formats supported in Python's standard library:

          - ``MH``
          - ``Babyl``
          - ``MMDF``
    """
    box_format = None

    # Validates folder as a maildir.
    if path.is_dir():
        for subdir in MAILDIR_SUBDIRS:
            if not path.joinpath(subdir).is_dir():
                raise ValueError(f"Missing sub-directory {subdir!r}")
        box_format = BoxFormat.MAILDIR

    # Validates folder as an mbox.
    elif path.is_file():
        box_format = BoxFormat.MBOX

    if not box_format:
        raise ValueError("Unrecognized mail source type.")

    logging.info(f"{theme.choice(str(box_format))} detected.")
    return box_format


def open_box(
    path: Path,
    box_format: BoxFormat | None = None,
    force_unlock: bool = False,
) -> list[Mailbox]:
    """Open a mail box.

    Returns a list of boxes, one per sub-folder. All are locked, ready for operations.

    If ``box_format`` is provided, forces the opening of the box in the specified format.
    Else, defaults to autodetection.
    """
    logging.info(f"\nOpening {theme.choice(str(path))} ...")
    if not box_format:
        box_format = autodetect_box_type(path)
    else:
        logging.warning(f"Forcing {box_format} format.")

    # Do not allow the constructor to create a new mailbox if not found.
    box = box_format.constructor(path, create=False)

    return open_subfolders(box, force_unlock)


def lock_box(box: Mailbox, force_unlock: bool) -> Mailbox:
    """Lock an opened box and allows for forced unlocking.

    Returns the locked box.
    """
    try:
        logging.debug("Locking box...")
        box.lock()
    except ExternalClashError:
        if not force_unlock:
            logging.error("Box already locked!")
            raise
        logging.warning("Box already locked! Forcing removal of lock...")
        box._locked = True  # type: ignore[attr-defined]
        box.unlock()
        box.lock()
    logging.debug("Box opened.")
    return box


FOLDER_FORMAT_CLASSES = frozenset(b.base_class for b in FOLDER_FORMATS)
"""Base classes of folder-based box formats."""


def open_subfolders(box: Mailbox, force_unlock: bool) -> list[Mailbox]:
    """Browse recursively the subfolder tree of a box.

    Returns a list of opened and locked boxes, each for one subfolder.

    Skips box types not supporting subfolders.
    """
    folder_list = [lock_box(box, force_unlock)]

    if isinstance(box, tuple(FOLDER_FORMAT_CLASSES)):
        # Asserts to please the type checker.
        assert hasattr(box, "list_folders")
        assert hasattr(box, "get_folder")
        for folder_id in box.list_folders():
            logging.info(f"Opening subfolder {folder_id} ...")
            folder_list += open_subfolders(box.get_folder(folder_id), force_unlock)
    return folder_list


def create_box(
    path: Path,
    box_format: BoxFormat,
    export_append: bool = False,
) -> Mailbox:
    """Creates a brand new box from scratch."""
    logging.info(
        f"Creating new {theme.choice(str(box_format))} box "
        f"at {theme.choice(str(path))} ..."
    )

    if path.exists() and export_append is not True:
        raise FileExistsError(path)

    # Allow the constructor to create a new mail box as we already double-checked
    # beforehand it does not exist.
    box: Mailbox = box_format.constructor(path, create=True)

    logging.debug("Locking box...")
    box.lock()
    return box
