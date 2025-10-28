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
import mailbox as py_mailbox
from enum import Enum, StrEnum
from functools import partial

from click_extra.colorize import default_theme as theme

from .mail import DedupMail

TYPE_CHECKING = False
if TYPE_CHECKING:
    from pathlib import Path
    from typing import Literal


class BoxStructure(StrEnum):
    """Box structures can be file-based or folder-based."""

    FILE = "file"
    FOLDER = "folder"


class BoxFormat(Enum):
    """IDs of all the supported box formats and their metadata.

    Each entry is associated to their original base class, and the structure they
    implement (file-based or folder-based).

    From these, we can derive the proper constructor with our own custom ``DedupMail``
    factory.

    .. hint::
        This could be extended in the future to add support for other mailbox formats
        and sources, like Gmail accounts, IMAP servers, etc.
    """

    # Same order as in `mailbox` module documentation.
    MAILDIR = (py_mailbox.Maildir, BoxStructure.FOLDER)
    MBOX = (py_mailbox.mbox, BoxStructure.FILE)
    MH = (py_mailbox.MH, BoxStructure.FOLDER)
    BABYL = (py_mailbox.Babyl, BoxStructure.FILE)
    MMDF = (py_mailbox.MMDF, BoxStructure.FILE)

    def __init__(
        self, base_class: type[py_mailbox.Mailbox], structure: BoxStructure
    ) -> None:
        self.base_class = base_class
        self.structure = structure

        # We expect the message class to be named as <BaseClass>Name.
        self.message_class = getattr(py_mailbox, f"{base_class.__name__}Message")

    def __str__(self):
        """The lowercase name of the format is used as a key in CLI options."""
        return self.name.lower()

    @property
    def constructor(self):
        """Wrap a subclass of ``mailbox.Message`` with our own ``DedupMail`` class."""
        factory_klass = type(
            f"{self.base_class.__name__}DedupMail",
            (DedupMail, self.message_class, object),
            {
                "__doc__": f"Extend the default message factory for {self.base_class} "
                "with our own ``DedupMail`` class to add deduplication utilities.",
            },
        )
        return partial(self.base_class, factory=factory_klass, create=False)


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

    logging.info(f"{theme.choice(box_format)} detected.")
    return box_format


def open_box(
    path: Path,
    box_format: BoxFormat | Literal[False] = False,
    force_unlock: bool = False,
) -> list[py_mailbox.Mailbox]:
    """Open a mail box.

    Returns a list of boxes, one per sub-folder. All are locked, ready for operations.

    If ``box_type`` is provided, forces the opening of the box in the specified format.
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


def lock_box(box: py_mailbox.Mailbox, force_unlock: bool) -> py_mailbox.Mailbox:
    """Lock an opened box and allows for forced unlocking.

    Returns the locked box.
    """
    try:
        logging.debug("Locking box...")
        box.lock()
    except py_mailbox.ExternalClashError:
        logging.error("Box already locked!")
        # Remove the lock manually and re-lock.
        if force_unlock:
            logging.warning("Forcing removal of lock...")
            # Forces internal metadata.
            box._locked = True
            box.unlock()
            box.lock()
        # Re-raise error.
        else:
            raise
    logging.debug("Box opened.")
    return box


def open_subfolders(
    box: py_mailbox.Mailbox,
    force_unlock: bool,
) -> list[py_mailbox.Mailbox]:
    """Browse recursively the subfolder tree of a box.

    Returns a list of opened and locked boxes, each for one subfolder.

    Skips box types not supporting subfolders.
    """
    folder_list = [lock_box(box, force_unlock)]

    if hasattr(box, "list_folders"):
        for folder_id in box.list_folders():
            logging.info(f"Opening subfolder {folder_id} ...")
            folder_list += open_subfolders(box.get_folder(folder_id), force_unlock)
    return folder_list


def create_box(
    path: Path,
    box_format: BoxFormat,
    export_append: bool = False,
) -> py_mailbox.Mailbox:
    """Creates a brand new box from scratch."""
    logging.info(
        f"Creating new {theme.choice(box_format)} box at {theme.choice(str(path))} ...",
    )

    if path.exists() and export_append is not True:
        raise FileExistsError(path)

    # Allow the constructor to create a new mail box as we already double-checked
    # beforehand it does not exist.
    box = box_format.constructor(path, create=True)

    logging.debug("Locking box...")
    box.lock()
    return box
