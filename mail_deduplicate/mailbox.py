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

"""Patch and tweak `Python's standard library mail box constructors.

<https://docs.python.org/3.11/library/mailbox.html>`_ to set sane defaults.

Also forces out our own message factories to add deduplication tools and utilities.
"""

from __future__ import annotations

import inspect
import mailbox
from functools import partial
from pathlib import Path

from boltons.dictutils import FrozenDict
from boltons.iterutils import flatten
from click_extra.colorize import default_theme as theme

from . import logger
from .mail import DedupMail


def build_box_constructors():
    """Build our own mail constructors for each subclass of ``mailbox.Mailbox``.

    Gather all constructors defined by the standard Python library and extend them with
    our ``DedupMail`` class.
    """
    # Only keep subclasses of the ``mailbox.Mailbox`` interface, but the latter and
    # all others starting with an underscore.
    for _, klass in inspect.getmembers(mailbox, inspect.isclass):
        if (
            klass != mailbox.Mailbox
            and not klass.__name__.startswith("_")
            and issubclass(klass, mailbox.Mailbox)
        ):
            # Fetch the default factory for each mailbox type based on naming
            # conventions.
            message_klass = getattr(mailbox, f"{klass.__name__}Message")
            assert issubclass(message_klass, mailbox.Message)

            # Extend the default factory with DedupMail class.
            factory_klass = type(
                f"{klass.__name__}DedupMail",
                (DedupMail, message_klass, object),
                {
                    "__doc__": f"Extend the default message factory for {klass} with "
                    "our own ``DedupMail`` class to add deduplication utilities."
                },
            )

            # Set our own custom factory and safety options to default constructor.
            constructor = partial(klass, factory=factory_klass, create=False)

            # Generates our own box_type_id for use in CLI parameters.
            box_type_id = klass.__name__.lower()

            yield box_type_id, constructor


BOX_TYPES = FrozenDict(build_box_constructors())
"""Mapping between supported box type IDs and their constructors."""


BOX_STRUCTURES = FrozenDict(
    {
        "file": {"mbox", "mmdf", "babyl"},
        "folder": {"maildir", "mh"},
    }
)
"""Categorize each box type into its structure type."""


# Check we did not forgot any box type.
assert set(flatten(BOX_STRUCTURES.values())) == set(BOX_TYPES)


MAILDIR_SUBDIRS = frozenset(("cur", "new", "tmp"))
"""List of required sub-folders defining a properly structured maildir."""


def autodetect_box_type(path):
    """Auto-detect the format of the mailbox located at the provided path.

    Returns a box type as indexed in the `BOX_TYPES <https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.mailbox.BOX_TYPES>`_ dictionnary above.

    If the path is a file, then it is considered as an ``mbox``. Else, if the
    provided path is a folder and feature the `expecteed sub-directories <https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.mailbox.MAILDIR_SUBDIRS>`_, it is
    parsed as a ``maildir``.

    .. note::
        Future finer autodetection heuristics should be implemented here.

        Some ideas:
            * single mail from a ``maildir``
            * plain text mail content
            * other mailbox formats supported in Python's standard library:
                * ``MH``
                * ``Babyl``
                * ``MMDF``
    """
    box_type = None

    # Validates folder as a maildir.
    if path.is_dir():
        for subdir in MAILDIR_SUBDIRS:
            if not path.joinpath(subdir).is_dir():
                raise ValueError(f"Missing sub-directory {subdir!r}")
        box_type = "maildir"

    # Validates folder as an mbox.
    elif path.is_file():
        box_type = "mbox"

    if not box_type:
        raise ValueError("Unrecognized mail source type.")

    logger.info(f"{theme.choice(box_type)} detected.")
    return box_type


def open_box(path, box_type=False, force_unlock=False):
    """Open a mail box.

    Returns a list of boxes, one per sub-folder. All are locked, ready for operations.

    If ``box_type`` is provided, forces the opening of the box in the specified format. Else, defaults to autodetection.
    """
    logger.info(f"\nOpening {theme.choice(path)} ...")
    path = Path(path)
    if not box_type:
        box_type = autodetect_box_type(path)
    else:
        logger.warning(f"Forcing {box_type} format.")

    constructor = BOX_TYPES[box_type]
    # Do not allow the constructor to create a new mailbox if not found.
    box = constructor(path, create=False)

    return open_subfolders(box, force_unlock)


def lock_box(box, force_unlock):
    """Lock an opened box and allows for forced unlocking.

    Returns the locked box.
    """
    try:
        logger.debug("Locking box...")
        box.lock()
    except mailbox.ExternalClashError:
        logger.error("Box already locked!")
        # Remove the lock manually and re-lock.
        if force_unlock:
            logger.warning("Forcing removal of lock...")
            # Forces internal metadata.
            box._locked = True
            box.unlock()
            box.lock()
        # Re-raise error.
        else:
            raise
    logger.debug("Box opened.")
    return box


def open_subfolders(box, force_unlock):
    """Browse recursively the subfolder tree of a box.

    Returns a list of opened and locked boxes, each for one subfolder.

    Skips box types not supporting subfolders.
    """
    folder_list = [lock_box(box, force_unlock)]

    if hasattr(box, "list_folders"):
        for folder_id in box.list_folders():
            logger.info(f"Opening subfolder {folder_id} ...")
            folder_list += open_subfolders(box.get_folder(folder_id), force_unlock)
    return folder_list


def create_box(path, box_type=False, export_append=False):
    """Creates a brand new box from scratch."""
    assert isinstance(path, Path)
    logger.info(
        f"Creating new {theme.choice(box_type)} box at {theme.choice(str(path))} ..."
    )

    if path.exists() and export_append is not True:
        raise FileExistsError(path)

    constructor = BOX_TYPES[box_type]
    # Allow the constructor to create a new mail box as we already double-checked
    # beforehand it does not exist.
    box = constructor(path, create=True)

    logger.debug("Locking box...")
    box.lock()
    return box
