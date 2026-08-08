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

Based on [Python's standard library mailbox module](https://docs.python.org/3.11/library/mailbox.html).
"""

from __future__ import annotations

import logging
import mailbox
import os
from collections.abc import Callable, Iterator
from enum import Enum, auto
from functools import partial
from mailbox import MH, MMDF, Babyl, ExternalClashError, Mailbox, Maildir, mbox
from pathlib import Path
from typing import cast
from uuid import uuid4

from click_extra import get_current_theme

from .mail import DedupMailMixin


def maildir_mail_path(box: Mailbox, key: str) -> str:
    """Location of a `maildir` mail, read from the box's table of contents.

    A maildir key drops the `:2,<flags>` suffix the file name carries, so the name
    cannot be rebuilt from the key alone. The box refreshed its table of contents to
    hand out the mail in the first place, so it is only re-validated on a miss.
    """
    try:
        subpath = box._toc[key]  # type: ignore[attr-defined]
    except KeyError:
        subpath = box._lookup(key)  # type: ignore[attr-defined]
    return os.path.join(box._path, subpath)


def keyed_mail_path(box: Mailbox, key: str) -> str:
    """Location of an `MH` or `eml` mail, whose file is named after its key."""
    return os.path.join(box._path, str(key))


def box_file_path(box: Mailbox, key: str) -> str:
    """Location of a mail from a file-based box: the box's own single file.

    Every mail of an `mbox`, `babyl` or `mmdf` box is packed into it, so they all
    share this path and are told apart by their mail ID.
    """
    return box._path


def iter_mail_ids(box: Mailbox) -> Iterator[str]:
    """Yields the key of every mail held by a box.

    `Maildir.iterkeys()` confirms that each key still resolves to a file, one `stat`
    per mail, on top of the directory listing it has just built. Every caller here
    goes on to stat or open that same file anyway, and copes with its disappearance,
    so the check is paid for twice and needed once: reading the refreshed table of
    contents directly skips it.

    The other formats list their mails without that extra round, and are left to
    their own iterator.
    """
    if isinstance(box, Maildir):
        box._refresh()  # type: ignore[attr-defined]
        # Iterate a copy: any later refresh rebuilds the table in place.
        yield from list(box._toc)  # type: ignore[attr-defined]
    else:
        yield from box.iterkeys()


def resolve_mail_path(box: Mailbox, key: str) -> str:
    """Location of a mail in its box, without instantiating the mail.

    Lets a caller reach a mail's file before deciding to read it, which is how the
    hash cache checks whether a mail changed without paying for its parsing.
    """
    factory = box._factory
    assert factory is not None, "Box opened without a DedupMail factory."
    return cast("str", factory.resolve_path(box, key))  # type: ignore[attr-defined]


def make_dedup_mail(
    name: str,
    base: type,
    path_resolver: Callable[[Mailbox, str], str],
) -> type:
    """Create a DedupMail class for a mailbox message type.

    Deriving a mail's own location from its box is format-specific, so the resolver
    is baked into the class here instead of being branched on at runtime.
    """
    return type(
        name,
        (DedupMailMixin, base),
        {"resolve_path": staticmethod(path_resolver)},
    )


MaildirDedupMail = make_dedup_mail(
    "MaildirDedupMail", mailbox.MaildirMessage, maildir_mail_path
)
mboxDedupMail = make_dedup_mail("mboxDedupMail", mailbox.mboxMessage, box_file_path)
MHDedupMail = make_dedup_mail("MHDedupMail", mailbox.MHMessage, keyed_mail_path)
BabylDedupMail = make_dedup_mail("BabylDedupMail", mailbox.BabylMessage, box_file_path)
MMDFDedupMail = make_dedup_mail("MMDFDedupMail", mailbox.MMDFMessage, box_file_path)
EMLDedupMail = make_dedup_mail("EMLDedupMail", mailbox.Message, keyed_mail_path)


class EML(Mailbox):
    """A folder of loose `.eml` files, walked recursively.

    Supports mail archives exported as individual RFC 5322 files, one mail per
    file, as produced by Outlook PST/OST conversion tools for instance. See:
    https://github.com/kdeldycke/mail-deduplicate/issues/760

    Keys are the paths of the mail files, relative to the folder's root. Files
    without the `.eml` extension (case-insensitive) are ignored, as well as
    hidden files and directories.

    Follows the interface of Python's [mailbox.Mailbox](https://docs.python.org/3/library/mailbox.html#mailbox.Mailbox). Like
    `maildir`, the one-file-per-mail storage needs no locking.
    """

    def __init__(self, dirname, factory=None, create=True) -> None:
        super().__init__(dirname, factory, create)
        if not os.path.exists(self._path):
            if create:
                os.mkdir(self._path, 0o700)
            else:
                raise mailbox.NoSuchMailboxError(self._path)

    def _full_path(self, key: str) -> str:
        return os.path.join(self._path, key)

    def iterkeys(self):
        for dirpath, dirnames, filenames in os.walk(self._path):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for filename in sorted(filenames):
                if not filename.startswith(".") and filename.lower().endswith(".eml"):
                    yield os.path.relpath(os.path.join(dirpath, filename), self._path)

    def __contains__(self, key) -> bool:
        return key.lower().endswith(".eml") and os.path.isfile(self._full_path(key))

    def __len__(self) -> int:
        return sum(1 for _ in self.iterkeys())

    def get_file(self, key):
        try:
            file = open(self._full_path(key), "rb")  # noqa: SIM115
        except FileNotFoundError:
            raise KeyError(key) from None
        # A BufferedReader covers _ProxyFile's runtime needs; typeshed's stricter
        # _GetFileReturn protocol (read1/readlines typed with int | None) rejects it.
        return mailbox._ProxyFile(file)  # type: ignore[arg-type]

    def get_bytes(self, key) -> bytes:
        try:
            with open(self._full_path(key), "rb") as file:
                return file.read()
        except FileNotFoundError:
            raise KeyError(key) from None

    def get_message(self, key):
        return mailbox.Message(self.get_bytes(key))

    def add(self, message) -> str:
        key = f"{uuid4().hex}.eml"
        # Write the raw message bytes with LF line endings. The stdlib
        # `_dump_message` rewrites `\n` to `os.linesep`, which emits CRLF on Windows
        # and makes the same mail serialize (and hash) differently across platforms.
        with open(self._full_path(key), "wb") as file:
            if isinstance(message, (bytes, bytearray)):
                file.write(message)
            else:
                file.write(message.as_bytes())
        return key

    def remove(self, key) -> None:
        try:
            os.remove(self._full_path(key))
        except FileNotFoundError:
            raise KeyError(key) from None

    def __setitem__(self, key, message) -> None:
        """Replacing a mail in place is not supported.

        `EML` keys are content paths and new mails get a fresh UUID filename from
        `add()`, so there is no meaningful in-place replacement by key. Overriding
        the abstract `mailbox.Mailbox.__setitem__` (which already raises) keeps the
        class concrete and instantiable, matching `get_folder` below.
        """
        raise NotImplementedError("EML mails are added and removed, not replaced.")

    def list_folders(self) -> list[str]:
        """No dedicated subfolder objects: the recursive walk covers nested
        directories."""
        return []

    def get_folder(self, folder):
        raise NotImplementedError("EML folders are walked recursively instead.")

    def flush(self) -> None:
        """Mails are written straight to the filesystem: nothing to flush."""

    def lock(self) -> None:
        """One-file-per-mail storage needs no locking."""

    def unlock(self) -> None:
        """One-file-per-mail storage needs no locking."""

    def close(self) -> None:
        """No resource is kept open between operations."""


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

    From these, we can derive the proper constructor with our own custom `DedupMail`
    factory.

    ```{hint}
    This could be extended in the future to add support for other mailbox formats
    and sources, like Gmail accounts, IMAP servers, etc.
    ```
    """

    # Same order as in `mailbox` module documentation.
    MAILDIR = (Maildir, BoxStructure.FOLDER, MaildirDedupMail)
    MBOX = (mbox, BoxStructure.FILE, mboxDedupMail)
    MH = (MH, BoxStructure.FOLDER, MHDedupMail)
    BABYL = (Babyl, BoxStructure.FILE, BabylDedupMail)
    MMDF = (MMDF, BoxStructure.FILE, MMDFDedupMail)
    # Custom format, not part of the standard library.
    EML = (EML, BoxStructure.FOLDER, EMLDedupMail)

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

Is a tuple to keep natural order defined by `BoxFormat`.
"""


FILE_FORMATS = tuple(box for box in BoxFormat if box.structure == BoxStructure.FILE)
"""Box formats implementing a file-based structure.

Is a tuple to keep natural order defined by `BoxFormat`.
"""


FOLDER_FORMAT_CLASSES = tuple(box.base_class for box in FOLDER_FORMATS)
"""Base classes of folder-based box formats, as a tuple ready for `isinstance`."""


MAILDIR_SUBDIRS = frozenset(("cur", "new", "tmp"))
"""List of required sub-folders defining a properly structured maildir."""


def is_maildir(path: Path) -> bool:
    """Returns `True` when the path holds all the sub-directories of a properly
    structured maildir."""
    return all(path.joinpath(subdir).is_dir() for subdir in MAILDIR_SUBDIRS)


def contains_maildir(path: Path) -> bool:
    """Returns `True` when the path is a maildir or holds one at any depth.

    Allows the discovery of nested maildir folders stored as plain directories, as
    produced by [isync/mbsync's Verbatim naming style](https://isync.sourceforge.io/mbsync.html). See:
    https://github.com/kdeldycke/mail-deduplicate/issues/973

    Dot-prefixed directories are ignored, as they are covered by the `Maildir++`
    folder convention. The mail-holding sub-directories of maildirs are not
    explored either.
    """
    if is_maildir(path):
        return True
    return any(
        contains_maildir(sub)
        for sub in path.iterdir()
        if sub.is_dir()
        and not sub.name.startswith(".")
        and sub.name not in MAILDIR_SUBDIRS
    )


def contains_eml(path: Path) -> bool:
    """Returns `True` when the path holds at least one `.eml` file, at any depth.

    Hidden files and directories are ignored, and the extension is matched
    case-insensitively, mirroring the walk of `EML` boxes.
    """
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if any(not f.startswith(".") and f.lower().endswith(".eml") for f in filenames):
            return True
    return False


def autodetect_box_type(path: Path) -> BoxFormat:
    """Auto-detect the format of the mailbox located at the provided path.

    If the path is a file, then it is considered as an `mbox`. Else, if the
    provided path is a folder and features the `MAILDIR_SUBDIRS` sub-directories,
    or holds nested maildir folders at any depth, it is parsed as a `maildir`.
    A folder holding loose `.eml` files instead is parsed as an `eml` source.

    ```{todo}
    Future finer autodetection heuristics should be implemented here. Some ideas:

    - single mail from a `maildir`
    - plain text mail content
    - other mailbox formats supported in Python's standard library:

      - `MH`
      - `Babyl`
      - `MMDF`
    ```
    """
    box_format = None

    # Validates folder as a maildir, either by its own structure or by the nested
    # maildir folders it contains. Falls back to a folder of loose .eml files.
    if path.is_dir():
        if contains_maildir(path):
            box_format = BoxFormat.MAILDIR
        elif contains_eml(path):
            box_format = BoxFormat.EML
        else:
            raise ValueError(
                f"Unrecognized folder: no {'/'.join(sorted(MAILDIR_SUBDIRS))} "
                "maildir structure, no nested maildir folders, and no .eml files "
                "found. Force a format with --input-format."
            )

    # A single file is read as an mbox.
    elif path.is_file():
        box_format = BoxFormat.MBOX

    if not box_format:
        raise ValueError("Unrecognized mail source type.")

    logging.info(f"{get_current_theme().choice(str(box_format))} detected.")
    return box_format


def open_box(
    path: Path,
    box_format: BoxFormat | None = None,
    force_unlock: bool = False,
) -> list[Mailbox]:
    """Open a mail box.

    Returns a list of boxes, one per sub-folder. All are locked, ready for operations.

    If `box_format` is provided, forces the opening of the box in the specified format.
    Else, defaults to autodetection.
    """
    logging.info(f"\nOpening {get_current_theme().choice(str(path))} ...")
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
            # Release the file handle before aborting. On Windows a lingering open
            # handle keeps the box file locked, so a later `--force-unlock` run in the
            # same process cannot rewrite it (WinError 32).
            box.close()
            raise
        logging.warning("Box already locked! Forcing removal of lock...")
        box._locked = True  # type: ignore[attr-defined]
        box.unlock()
        box.lock()
    logging.debug("Box opened.")
    return box


def open_subfolders(box: Mailbox, force_unlock: bool) -> list[Mailbox]:
    """Browse recursively the subfolder tree of a box.

    Returns a list of opened and locked boxes, each for one subfolder.

    Skips box types not supporting subfolders. For `maildir`, both the
    `Maildir++` convention (dot-prefixed folders) and Verbatim-style layouts
    (nested plain directories, each a maildir of its own) are browsed. A directory
    without the maildir structure only acts as a container of nested folders and
    carries no mail of its own.
    """
    folder_list = []

    if isinstance(box, Maildir) and not is_maildir(Path(box._path)):
        logging.info("No mails at this level: only browse nested folders.")
    else:
        folder_list.append(lock_box(box, force_unlock))

    if isinstance(box, FOLDER_FORMAT_CLASSES):
        # Asserts to please the type checker.
        assert hasattr(box, "list_folders")
        assert hasattr(box, "get_folder")
        for folder_id in box.list_folders():
            logging.info(f"Opening subfolder {folder_id} ...")
            folder_list += open_subfolders(box.get_folder(folder_id), force_unlock)

        # Python's mailbox module only lists dot-prefixed Maildir++ folders, so
        # browse the filesystem for Verbatim-style nested maildir folders.
        if isinstance(box, Maildir):
            for sub_path in sorted(Path(box._path).iterdir()):
                if (
                    sub_path.is_dir()
                    and not sub_path.name.startswith(".")
                    and sub_path.name not in MAILDIR_SUBDIRS
                    and contains_maildir(sub_path)
                ):
                    logging.info(f"Opening subfolder {sub_path.name} ...")
                    sub_box = Maildir(sub_path, factory=box._factory, create=False)
                    folder_list += open_subfolders(sub_box, force_unlock)
    return folder_list


def create_box(
    path: Path,
    box_format: BoxFormat,
    export_append: bool = False,
) -> Mailbox:
    """Creates a brand new box from scratch."""
    theme = get_current_theme()
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
