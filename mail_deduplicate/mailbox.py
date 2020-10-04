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

from . import logger
from .mail import Mail


""" Patch and tweak Python's standard librabry mailboxes constructors to set
sane defaults. Also forces out our own message factories to add deduplication
tools and utilities. """


# List of required sub-folders defining a properly structured maildir.
MAILDIR_SUBDIRS = frozenset(("cur", "new", "tmp"))


# Maintain a mapping between box type IDs and their constructors.
box_types = {}

# Gather all constructors specific mailbox formats supported by the standard
# Python library.
for _, klass in inspect.getmembers(mailbox, inspect.isclass):
    # Only keep subclasses of the mailbox.Mailbox interface, but the latter and
    # all others starting with an underscore.
    if (
        klass != mailbox.Mailbox
        and not klass.__name__.startswith("_")
        and issubclass(klass, mailbox.Mailbox)
    ):
        box_types[klass.__name__.lower()] = klass


def autodetect_box_type(source_path):
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
    logger.info(f"Opening {source_path} and auto-detect format...")

    if source_path.is_dir():
        logger.info("Maildir detected.")

        # Validates folder is a maildir.
        for subdir in MAILDIR_SUBDIRS:
            if not source_path.joinpath(subdir).is_dir():
                raise ValueError(f"Missing sub-directory {subdir!r}")

        return "maildir"

    if source_path.is_file():
        logger.info("mbox detected.")
        return "mbox"

    raise ValueError("Unrecognized mail source type.")
