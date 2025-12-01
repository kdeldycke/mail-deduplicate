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
"""Strategy definitions."""

from __future__ import annotations

import enum
import logging
import random
import re
from functools import wraps

from click_extra.colorize import default_theme as theme

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Callable, TypeAlias

    from .deduplicate import DuplicateSet
    from .mail import DedupMailMixin

    SelectionFunc: TypeAlias = Callable[[DuplicateSet], set[DedupMailMixin]]


def log_selection(message_template: str):
    """Decorator to log selection criteria."""

    def decorator(func: SelectionFunc) -> SelectionFunc:
        @wraps(func)
        def wrapper(duplicates: DuplicateSet) -> set[DedupMailMixin]:
            logging.info(message_template.format(d=duplicates))
            return func(duplicates)

        return wrapper

    return decorator


@log_selection(
    "Select all mails strictly older than the {d.newest_timestamp} timestamp..."
)
def select_older(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all older duplicates.

    Discards the newests, i.e. the subset sharing the most recent timestamp.
    """
    return {
        mail for mail in duplicates.pool if mail.timestamp < duplicates.newest_timestamp
    }


@log_selection("Select all mails sharing the oldest {d.oldest_timestamp} timestamp...")
def select_oldest(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all the oldest duplicates.

    Discards the newers, i.e. all mail of the duplicate set but those sharing the oldest
    timestamp.
    """
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.oldest_timestamp
    }


@log_selection(
    "Select all mails strictly newer than the {d.oldest_timestamp} timestamp..."
)
def select_newer(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all newer duplicates.

    Discards the oldest, i.e. the subset sharing the most ancient timestamp.
    """
    return {
        mail for mail in duplicates.pool if mail.timestamp > duplicates.oldest_timestamp
    }


@log_selection("Select all mails sharing the newest {d.newest_timestamp} timestamp...")
def select_newest(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all the newest duplicates.

    Discards the olders, i.e. all mail of the duplicate set but those sharing the newest
    timestamp.
    """
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.newest_timestamp
    }


@log_selection("Select all mails strictly smaller than {d.biggest_size} bytes...")
def select_smaller(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all smaller duplicates.

    Discards the biggests, i.e. the subset sharing the biggest size.
    """
    return {mail for mail in duplicates.pool if mail.size < duplicates.biggest_size}


@log_selection(
    "Select all mails sharing the smallest size of {d.smallest_size} bytes..."
)
def select_smallest(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all the smallest duplicates.

    Discards the biggers. i.e. all mail of the duplicate set but those sharing the
    smallest size.
    """
    return {mail for mail in duplicates.pool if mail.size == duplicates.smallest_size}


@log_selection("Select all mails strictly bigger than {d.smallest_size} bytes...")
def select_bigger(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all bigger duplicates.

    Discards the smallests, i.e. the subset sharing the smallest size.
    """
    return {mail for mail in duplicates.pool if mail.size > duplicates.smallest_size}


@log_selection("Select all mails sharing the biggest size of {d.biggest_size} bytes...")
def select_biggest(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all the biggest duplicates.

    Discards the smallers, i.e. all mail of the duplicate set but those sharing the
    biggest size.
    """
    return {mail for mail in duplicates.pool if mail.size == duplicates.biggest_size}


@log_selection(
    "Select all mails with file path matching the {d.conf[regexp].pattern} regexp..."
)
def select_matching_path(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all duplicates whose file path match the regular expression provided via
    the --regexp parameter."""
    assert duplicates.conf["regexp"] is not None
    return {
        mail
        for mail in duplicates.pool
        if re.search(duplicates.conf["regexp"], mail.path)
    }


@log_selection(
    "Select all mails with file path not matching the {d.conf[regexp].pattern} regexp..."
)
def select_non_matching_path(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Select all duplicates whose file path doesn't match the regular expression
    provided via the --regexp parameter."""
    assert duplicates.conf["regexp"] is not None
    return {
        mail
        for mail in duplicates.pool
        if not re.search(duplicates.conf["regexp"], mail.path)
    }


@log_selection("Randomly select one duplicate...")
def select_one(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Randomly select one duplicate, and discards all others."""
    return {random.choice(tuple(duplicates.pool))}


@log_selection("Randomly select all but one duplicate...")
def select_all_but_one(duplicates: DuplicateSet) -> set[DedupMailMixin]:
    """Randomly discard one duplicate, and select all others."""
    return set(random.sample(tuple(duplicates.pool), k=len(duplicates.pool) - 1))


@enum.unique
class Strategy(enum.Enum):
    """Selection strategies to apply on a sets of duplicate mails.

    Each strategy in the ``Enum`` points to the function implementing the selection
    logic, by the way of the ``strategy_function()`` method.

    Strategies whose member value is a string are simply aliases to other strategies,
    pointing to the name of the function implementing the logic. The other members have
    integer values, to indicate their function ID is to be derived from the member name.
    This arrangement allow for each member to have its own existence without being
    hidden by the aliasing mechanism of ``Enum``.

    Aliases are great usability features to represent inverse operations. They helps
    users to better reason about the selection operators depending on their mental
    models.
    """

    # Time-based strategies.
    SELECT_OLDER = 1
    SELECT_OLDEST = 2
    SELECT_NEWER = 3
    SELECT_NEWEST = 4
    DISCARD_NEWEST = "select_older"
    DISCARD_NEWER = "select_oldest"
    DISCARD_OLDEST = "select_newer"
    DISCARD_OLDER = "select_newest"

    # Size-based strategies.
    SELECT_SMALLER = 5
    SELECT_SMALLEST = 6
    SELECT_BIGGER = 7
    SELECT_BIGGEST = 8
    DISCARD_BIGGEST = "select_smaller"
    DISCARD_BIGGER = "select_smallest"
    DISCARD_SMALLEST = "select_bigger"
    DISCARD_SMALLER = "select_biggest"

    # Location-based strategies.
    SELECT_MATCHING_PATH = 9
    SELECT_NON_MATCHING_PATH = 10
    DISCARD_NON_MATCHING_PATH = "select_matching_path"
    DISCARD_MATCHING_PATH = "select_non_matching_path"

    # Quantity-based strategies.
    SELECT_ONE = 11
    SELECT_ALL_BUT_ONE = 12
    DISCARD_ALL_BUT_ONE = "select_one"
    DISCARD_ONE = "select_all_but_one"

    def __str__(self):
        """Get the string to be used in CLI for the strategy."""
        return self.name.lower().replace("_", "-")

    @property
    def strategy_function(self) -> Callable:
        """Return the function's ID is the value of the ``Enum`` member."""
        if isinstance(self.value, str):
            func_id = self.value
        else:
            func_id = self.name.lower()
        return globals()[func_id]  # type: ignore[no-any-return]

    def apply_strategy(self, duplicates: DuplicateSet) -> set[DedupMailMixin]:
        """Perform the selection strategy on the provided duplicate set.

        Returns a set of selected mails objects.
        """
        logging.info(f"Apply {theme.choice(str(self))} strategy...")
        return set(self.strategy_function(duplicates))
