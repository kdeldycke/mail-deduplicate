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

import logging
import random
import re

from boltons.dictutils import FrozenDict


def select_older(duplicates):
    """Select all older duplicates.

    Discards the newests, i.e. the subset sharing the most recent timestamp.
    """
    logging.info(
        f"Select all mails strictly older than the {duplicates.newest_timestamp} "
        "timestamp...",
    )
    return {
        mail for mail in duplicates.pool if mail.timestamp < duplicates.newest_timestamp
    }


def select_oldest(duplicates):
    """Select all the oldest duplicates.

    Discards the newers, i.e. all mail of the duplicate set but those sharing the oldest
    timestamp.
    """
    logging.info(
        f"Select all mails sharing the oldest {duplicates.oldest_timestamp} "
        "timestamp...",
    )
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.oldest_timestamp
    }


def select_newer(duplicates):
    """Select all newer duplicates.

    Discards the oldest, i.e. the subset sharing the most ancient timestamp.
    """
    logging.info(
        f"Select all mails strictly newer than the {duplicates.oldest_timestamp} "
        "timestamp...",
    )
    return {
        mail for mail in duplicates.pool if mail.timestamp > duplicates.oldest_timestamp
    }


def select_newest(duplicates):
    """Select all the newest duplicates.

    Discards the olders, i.e. all mail of the duplicate set but those sharing the newest
    timestamp.
    """
    logging.info(
        f"Select all mails sharing the newest {duplicates.newest_timestamp} "
        "timestamp...",
    )
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.newest_timestamp
    }


def select_smaller(duplicates):
    """Select all smaller duplicates.

    Discards the biggests, i.e. the subset sharing the biggest size.
    """
    logging.info(
        f"Select all mails strictly smaller than {duplicates.biggest_size} bytes...",
    )
    return {mail for mail in duplicates.pool if mail.size < duplicates.biggest_size}


def select_smallest(duplicates):
    """Select all the smallest duplicates.

    Discards the biggers. i.e. all mail of the duplicate set but those sharing the
    smallest size.
    """
    logging.info(
        f"Select all mails sharing the smallest size of {duplicates.smallest_size} "
        "bytes...",
    )
    return {mail for mail in duplicates.pool if mail.size == duplicates.smallest_size}


def select_bigger(duplicates):
    """Select all bigger duplicates.

    Discards the smallests, i.e. the subset sharing the smallest size.
    """
    logging.info(
        f"Select all mails strictly bigger than {duplicates.smallest_size} bytes...",
    )
    return {mail for mail in duplicates.pool if mail.size > duplicates.smallest_size}


def select_biggest(duplicates):
    """Select all the biggest duplicates.

    Discards the smallers, i.e. all mail of the duplicate set but those sharing the
    biggest size.
    """
    logging.info(
        f"Select all mails sharing the biggest size of {duplicates.biggest_size} "
        "bytes...",
    )
    return {mail for mail in duplicates.pool if mail.size == duplicates.biggest_size}


def select_matching_path(duplicates):
    """Select all duplicates whose file path match the regular expression provided via
    the --regexp parameter."""
    logging.info(
        "Select all mails with file path matching the "
        f"{duplicates.conf.regexp.pattern} regexp...",
    )
    return {
        mail for mail in duplicates.pool if re.search(duplicates.conf.regexp, mail.path)
    }


def select_non_matching_path(duplicates):
    """Select all duplicates whose file path doesn't match the regular expression
    provided via the --regexp parameter."""
    logging.info(
        "Select all mails with file path not matching the "
        f"{duplicates.conf.regexp.pattern} regexp...",
    )
    return {
        mail
        for mail in duplicates.pool
        if not re.search(duplicates.conf.regexp, mail.path)
    }


def select_one(duplicates):
    """Randomly select one duplicate, and discards all others."""
    return {random.choice(tuple(duplicates.pool))}


def select_all_but_one(duplicates):
    """Randomly discard one duplicate, and select all others."""
    return set(random.sample(tuple(duplicates.pool), k=len(duplicates.pool) - 1))


# Use symbols to define selection strategies.

DISCARD_OLDER = "discard-older"
DISCARD_OLDEST = "discard-oldest"
DISCARD_NEWER = "discard-newer"
DISCARD_NEWEST = "discard-newest"
SELECT_OLDER = "select-older"
SELECT_OLDEST = "select-oldest"
SELECT_NEWER = "select-newer"
SELECT_NEWEST = "select-newest"
"""Time-based strategies."""

DISCARD_SMALLER = "discard-smaller"
DISCARD_SMALLEST = "discard-smallest"
DISCARD_BIGGER = "discard-bigger"
DISCARD_BIGGEST = "discard-biggest"
SELECT_SMALLER = "select-smaller"
SELECT_SMALLEST = "select-smallest"
SELECT_BIGGER = "select-bigger"
SELECT_BIGGEST = "select-biggest"
"""Size-based strategies."""

DISCARD_MATCHING_PATH = "discard-matching-path"
DISCARD_NON_MATCHING_PATH = "discard-non-matching-path"
SELECT_MATCHING_PATH = "select-matching-path"
SELECT_NON_MATCHING_PATH = "select-non-matching-path"
"""Location-based strategies."""

DISCARD_ONE = "discard-one"
DISCARD_ALL_BUT_ONE = "discard-all-but-one"
SELECT_ONE = "select-one"
SELECT_ALL_BUT_ONE = "select-all-but-one"
"""Quantity-based strategies."""


STRATEGY_ALIASES = frozenset(
    [
        (SELECT_NEWEST, DISCARD_OLDER),
        (SELECT_NEWER, DISCARD_OLDEST),
        (SELECT_OLDEST, DISCARD_NEWER),
        (SELECT_OLDER, DISCARD_NEWEST),
        (SELECT_BIGGEST, DISCARD_SMALLER),
        (SELECT_BIGGER, DISCARD_SMALLEST),
        (SELECT_SMALLEST, DISCARD_BIGGER),
        (SELECT_SMALLER, DISCARD_BIGGEST),
        (SELECT_NON_MATCHING_PATH, DISCARD_MATCHING_PATH),
        (SELECT_MATCHING_PATH, DISCARD_NON_MATCHING_PATH),
        (SELECT_ALL_BUT_ONE, DISCARD_ONE),
        (SELECT_ONE, DISCARD_ALL_BUT_ONE),
    ],
)
"""Groups strategy aliases and their definitions.

Aliases are great usability features as it helps users to better reason about the
selection operators depending on their mental models.
"""


def get_method_id(strategy_id):
    """Transform strategy ID to its method ID."""
    return strategy_id.replace("-", "_")


def build_method_mapping():
    """Precompute the mapping of all strategy IDs to their preferred method name,
    including aliases as fallbacks."""
    methods = {}
    for strategies in STRATEGY_ALIASES:
        fallback_method = None
        for strategy_id in strategies:
            mid = get_method_id(strategy_id)
            method = globals().get(mid)
            if method:
                fallback_method = method
            if not fallback_method:
                msg = f"Can't find {mid}() method."
                raise NotImplementedError(msg)
            methods[strategy_id] = fallback_method
    return methods


STRATEGY_METHODS = FrozenDict(build_method_mapping())


def apply_strategy(strategy_id, duplicates):
    """Perform the selection strategy on the provided duplicate set.

    Returns a set of selected mails objects.
    """
    if strategy_id not in STRATEGY_METHODS:
        msg = f"Unknown {strategy_id} strategy."
        raise ValueError(msg)
    method = STRATEGY_METHODS[strategy_id]
    logging.debug(f"Apply {method!r}...")
    return set(method(duplicates))
