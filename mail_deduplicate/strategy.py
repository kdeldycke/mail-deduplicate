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

""" Strategy definitions. """

import random
import re

from boltons.dictutils import FrozenDict

from . import logger


def discard_older(duplicates):
    """Discard all older duplicates.

    Only select the newests, i.e. the subset sharing the most recent timestamp.
    """
    logger.info(
        f"Select all mails strictly older than the {duplicates.newest_timestamp} "
        "timestamp..."
    )
    return {
        mail for mail in duplicates.pool if mail.timestamp < duplicates.newest_timestamp
    }


def discard_oldest(duplicates):
    """Discard all the oldest duplicates.

    Only select the newers, i.e. all mail of the duplicate set but those sharing
    the oldest timestamp.
    """
    logger.info(
        f"Select all mails sharing the oldest {duplicates.oldest_timestamp} "
        "timestamp..."
    )
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.oldest_timestamp
    }


def discard_newer(duplicates):
    """Discard all newer duplicates.

    Only select the oldest, i.e. the subset sharing the most ancient timestamp.
    """
    logger.info(
        f"Select all mails strictly newer than the {duplicates.oldest_timestamp} "
        "timestamp..."
    )
    return {
        mail for mail in duplicates.pool if mail.timestamp > duplicates.oldest_timestamp
    }


def discard_newest(duplicates):
    """Discard all the newest duplicates.

    Only select the olders, i.e. all mail of the duplicate set but those sharing the
    newest timestamp.
    """
    logger.info(
        f"Select all mails sharing the newest {duplicates.newest_timestamp} "
        "timestamp..."
    )
    return {
        mail
        for mail in duplicates.pool
        if mail.timestamp == duplicates.newest_timestamp
    }


def discard_smaller(duplicates):
    """Discard all smaller duplicates.

    Only select the biggests, i.e. the subset sharing the biggest size.
    """
    logger.info(
        f"Select all mails strictly smaller than {duplicates.biggest_size} bytes..."
    )
    return {mail for mail in duplicates.pool if mail.size < duplicates.biggest_size}


def discard_smallest(duplicates):
    """Discard all the smallest duplicates.

    Only select the biggers. i.e. all mail of the duplicate set but those sharing the
    smallest size.
    """
    logger.info(
        f"Select all mails sharing the smallest size of {duplicates.smallest_size} "
        "bytes..."
    )
    return {mail for mail in duplicates.pool if mail.size == duplicates.smallest_size}


def discard_bigger(duplicates):
    """Discard all bigger duplicates.

    Only select the smallests, i.e. the subset sharing the smallest size.
    """
    logger.info(
        f"Select all mails strictly bigger than {duplicates.smallest_size} bytes..."
    )
    return {mail for mail in duplicates.pool if mail.size > duplicates.smallest_size}


def discard_biggest(duplicates):
    """Discard all the biggest duplicates.

    Only select the smallers, i.e. all mail of the duplicate set but those sharing the
    biggest size.
    """
    logger.info(
        f"Select all mails sharing the biggest size of {duplicates.biggest_size} "
        "bytes..."
    )
    return {mail for mail in duplicates.pool if mail.size == duplicates.biggest_size}


def discard_matching_path(duplicates):
    """Discards all duplicates whose file path match the regular expression provided
    via the --regexp parameter.
    """
    logger.info(
        "Select all mails with file path matching the "
        f"{duplicates.conf.regexp.pattern} regexp..."
    )
    return {
        mail for mail in duplicates.pool if re.search(duplicates.conf.regexp, mail.path)
    }


def discard_non_matching_path(duplicates):
    """Discards all duplicates whose file path doesn't match the regular expression
    provided via the --regexp parameter.
    """
    logger.info(
        "Select all mails with file path not matching the "
        f"{duplicates.conf.regexp.pattern} regexp..."
    )
    return {
        mail
        for mail in duplicates.pool
        if not re.search(duplicates.conf.regexp, mail.path)
    }


def discard_one(duplicates):
    """Randomly discards one duplicate, and select all others."""
    return {random.choice(tuple(duplicates.pool))}


def discard_all_but_one(duplicates):
    """Randomly discards all duplicates, but select one."""
    return set(random.sample(duplicates.pool, k=len(duplicates.pool) - 1))


# Use symbols to define selection strategies.
DISCARD_OLDER = "discard-older"
DISCARD_OLDEST = "discard-oldest"
DISCARD_NEWER = "discard-newer"
DISCARD_NEWEST = "discard-newest"
SELECT_OLDER = "select-older"
SELECT_OLDEST = "select-oldest"
SELECT_NEWER = "select-newer"
SELECT_NEWEST = "select-newest"

DISCARD_SMALLER = "discard-smaller"
DISCARD_SMALLEST = "discard-smallest"
DISCARD_BIGGER = "discard-bigger"
DISCARD_BIGGEST = "discard-biggest"
SELECT_SMALLER = "select-smaller"
SELECT_SMALLEST = "select-smallest"
SELECT_BIGGER = "select-bigger"
SELECT_BIGGEST = "select-biggest"

DISCARD_MATCHING_PATH = "discard-matching-path"
DISCARD_NON_MATCHING_PATH = "discard-non-matching-path"
SELECT_MATCHING_PATH = "select-matching-path"
SELECT_NON_MATCHING_PATH = "select-non-matching-path"

DISCARD_ONE = "discard-one"
DISCARD_ALL_BUT_ONE = "discard-all-but-one"
SELECT_ONE = "select-one"
SELECT_ALL_BUT_ONE = "select-all-but-one"


# Groups strategy aliases and their definitions. Aliases are great useability
# features as it helps users to better reason about the selection operators
# dependening on their mental models.
STRATEGY_ALIASES = frozenset(
    [
        (DISCARD_OLDER, SELECT_NEWEST),
        (DISCARD_OLDEST, SELECT_NEWER),
        (DISCARD_NEWER, SELECT_OLDEST),
        (DISCARD_NEWEST, SELECT_OLDER),
        (DISCARD_SMALLER, SELECT_BIGGEST),
        (DISCARD_SMALLEST, SELECT_BIGGER),
        (DISCARD_BIGGER, SELECT_SMALLEST),
        (DISCARD_BIGGEST, SELECT_SMALLER),
        (DISCARD_MATCHING_PATH, SELECT_NON_MATCHING_PATH),
        (DISCARD_NON_MATCHING_PATH, SELECT_MATCHING_PATH),
        (DISCARD_ONE, SELECT_ALL_BUT_ONE),
        (DISCARD_ALL_BUT_ONE, SELECT_ONE),
    ]
)


def get_method_id(strat_id):
    """ Transform strategy ID to its method ID. """
    return strat_id.replace("-", "_")


def build_method_mapping():
    """Precompute the mapping of all strategy IDs to their prefered method name,
    including aliases as fallbacks.
    """
    methods = dict()
    for strategies in STRATEGY_ALIASES:
        fallback_method = None
        for strat_id in strategies:
            mid = get_method_id(strat_id)
            method = globals().get(mid)
            if method:
                fallback_method = method
            if not fallback_method:
                raise NotImplementedError(f"Can't find {mid}() method.")
            methods[strat_id] = fallback_method
    return methods


STRATEGY_METHODS = FrozenDict(build_method_mapping())


def apply_strategy(strat_id, duplicates):
    """Perform the selection strategy on the provided duplicate set.

    Returns a set of selected mails objects.
    """
    if strat_id not in STRATEGY_METHODS:
        raise ValueError(f"Unknown {strat_id} strategy.")
    method = STRATEGY_METHODS[strat_id]
    logger.debug(f"Apply {method!r}...")
    return set(method(duplicates))
