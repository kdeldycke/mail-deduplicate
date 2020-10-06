# -*- coding: utf-8 -*-
#
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

import mailbox
import inspect
from functools import partial
from pathlib import Path

import click
from boltons.dictutils import FrozenDict

from . import logger
from .mail import DedupMail


""" Patch and tweak Python's standard librabry mailboxes constructors to set
sane defaults. Also forces out our own message factories to add deduplication
tools and utilities. """


# List of required sub-folders defining a properly structured maildir.
MAILDIR_SUBDIRS = frozenset(("cur", "new", "tmp"))


def build_box_constructors():
    """Gather all constructors specific mailbox formats supported by the standard
    Python library.

    Only keep subclasses of the mailbox.Mailbox interface, but the latter and
    all others starting with an underscore.
    """
    for _, klass in inspect.getmembers(mailbox, inspect.isclass):
        if (
            klass != mailbox.Mailbox
            and not klass.__name__.startswith("_")
            and issubclass(klass, mailbox.Mailbox)
        ):
            # Fetch the default factory for each mailbox type based on naming
            # conventions .
            message_klass = getattr(mailbox, "{}Message".format(klass.__name__))
            assert issubclass(message_klass, mailbox.Message)

            # Extend the default factory with our own ``DedupMail`` class to add
            # deduplication utilities.
            factory_klass = type(
                "{}DedupMail".format(klass.__name__),
                (DedupMail, message_klass, object),
                {
                    "__doc__": f"Extend the default message factory for {klass} with our "
                    "own ``DedupMail`` class to add deduplication utilities."
                },
            )

            # Set our own custom factory and safety options to default constructor.
            constructor = partial(klass, factory=factory_klass, create=False)

            # Generates our own box_type_id for use in CLI parameters.
            box_type_id = klass.__name__.lower()

            yield box_type_id, constructor


# Mapping between supported box type IDs and their constructors.
BOX_TYPES = FrozenDict(build_box_constructors())


def autodetect_box_type(path):
    """Auto-detect the format of the mailbox located at the provided path.

    Returns a box type as indexed in the ``box_types`` dictionnary above.

    If the path is a file, then it is considered as an ``mbox``. Else, if th
    provided path is a folder and feature the expecteed sub-directories, it is
    parsed as a ``maildir``.

    Future finer autodetection heuristics should be implemented here. Some ideas:
        * single mail from a maildir
        * plain text mail content
        * other mailbox formats supported in Python's std lib:
            * ``MH``
            * ``Babyl``
            * ``MMDF``
    """
    box_type = None

    # Validates folder is a maildir.
    if path.is_dir():
        for subdir in MAILDIR_SUBDIRS:
            if not path.joinpath(subdir).is_dir():
                raise ValueError(f"Missing sub-directory {subdir!r}")
        box_type = "maildir"

    # Validates folder is a mbox.
    elif path.is_file():
        box_type = "mbox"

    if not box_type:
        raise ValueError("Unrecognized mail source type.")

    logger.info("{} detected.".format(click.style(box_type, fg="bright_white")))
    return box_type


def open_box(path, box_type=False, force_unlock=False):
    """Open a mailbox.

    Returns the locked box, ready for operations.

    If ``box_type`` is specified, forces the opening of the box in the
    specified format. Else try to autodetect the type.
    """
    styled_path = click.style(str(path), fg="bright_white")
    logger.info(f"Opening {styled_path} ...")
    assert isinstance(path, Path)
    if not box_type:
        box_type = autodetect_box_type(path)
    else:
        logger.warning(f"Forcing {box_type} format.")

    constructor = BOX_TYPES[box_type]
    box = constructor(path)

    try:
        logger.debug(f"Locking box...")
        box.lock()
    except mailbox.ExternalClashError:
        logger.error(f"Box already locked!")
        # Remove the lock manually and re-lock.
        if force_unlock:
            logger.warning(f"Forcing removal of lock...")
            # Forces internal metadata.
            box._locked = True
            box.unlock()
            box.lock()
        # Re-raise error.
        else:
            raise

    logger.debug(f"Box opened.")
    return box
