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

from operator import itemgetter

from boltons.iterutils import flatten
from boltons.dictutils import FrozenDict


# Use symbols to define selection strategies.
DISCARD_OLDER = "discard-older"
DISCARD_OLDEST = "discard-oldest"
DISCARD_NEWER = "discard-newer"
DISCARD_NEWEST = "discard-newest"
KEEP_OLDER = "keep-older"
KEEP_OLDEST = "keep-oldest"
KEEP_NEWER = "keep-newer"
KEEP_NEWEST = "keep-newest"

DISCARD_SMALLER = "discard-smaller"
DISCARD_SMALLEST = "discard-smallest"
DISCARD_BIGGER = "discard-bigger"
DISCARD_BIGGEST = "discard-biggest"
KEEP_SMALLER = "keep-smaller"
KEEP_SMALLEST = "keep-smallest"
KEEP_BIGGER = "keep-bigger"
KEEP_BIGGEST = "keep-biggest"

DISCARD_MATCHING_PATH = "discard-matching-path"
DISCARD_NON_MATCHING_PATH = "discard-non-matching-path"
KEEP_MATCHING_PATH = "keep-matching-path"
KEEP_NON_MATCHING_PATH = "keep-non-matching-path"

DISCARD_ONE = "discard-one"
DISCARD_ALL_BUT_ONE = "discard-all-but-one"
KEEP_ONE = "keep-one"
KEEP_ALL_BUT_ONE = "keep-all-but-one"


# Groups strategy aliases and their definitions. Aliases are great useability
# features as it helps users to better reason about the selection operators
# dependening on their mental models.
STRATEGY_DEFINITIONS = frozenset(
    [
        (
            (DISCARD_OLDER, KEEP_NEWEST),
            "Discards the olders, keeps the newests.",
        ),
        (
            (DISCARD_OLDEST, KEEP_NEWER),
            "Discards the oldests, keeps the newers.",
        ),
        (
            (DISCARD_NEWER, KEEP_OLDEST),
            "Discards the newers, keeps the oldests.",
        ),
        (
            (DISCARD_NEWEST, KEEP_OLDER),
            "Discards the newests, keeps the olders.",
        ),
        (
            (DISCARD_SMALLER, KEEP_BIGGEST),
            "Discards the smallers, keeps the biggests.",
        ),
        (
            (DISCARD_SMALLEST, KEEP_BIGGER),
            "Discards the smallests, keeps the biggers.",
        ),
        (
            (DISCARD_BIGGER, KEEP_SMALLEST),
            "Discards the biggers, keeps the smallests.",
        ),
        (
            (DISCARD_BIGGEST, KEEP_SMALLER),
            "Discards the biggests, keeps the smallers.",
        ),
        (
            (DISCARD_MATCHING_PATH, KEEP_NON_MATCHING_PATH),
            "Discards all duplicates whose file path match the regular "
            "expression provided via the --regexp parameter.",
        ),
        (
            (DISCARD_NON_MATCHING_PATH, KEEP_MATCHING_PATH),
            "Discards all duplicates whose file path doesn't match the regular "
            "expression provided via the --regexp parameter.",
        ),
        (
            (DISCARD_ONE, KEEP_ALL_BUT_ONE),
            "Randomly discards one duplicate, and keep all others.",
        ),
        (
            (DISCARD_ALL_BUT_ONE, KEEP_ONE),
            "Randomly discards all duplicates, but keep one.",
        ),
    ]
)

STRATEGIES = frozenset(flatten(map(itemgetter(0), STRATEGY_DEFINITIONS)))


def get_method_id(strat_id):
    """ Transform strategy ID to its method ID. """
    return strat_id.replace("-", "_")


def build_method_mapping():
    """Precompute the mapping of strategy IDs to their prefered method name, including
    aliases as fallbacks.
    """
    method_ids = dict()
    for strat_id in STRATEGIES:
        method_ids.setdefault(strat_id, []).append(get_method_id(strat_id))
        # Hunt for aliases.
        for aliases in map(itemgetter(0), STRATEGY_DEFINITIONS):
            if strat_id in aliases:
                for alias_id in aliases:
                    alias_mid = get_method_id(alias_id)
                    if alias_mid not in method_ids[strat_id]:
                        method_ids[strat_id].append(alias_mid)
    return method_ids


STRATEGY_METHOD_IDS = FrozenDict(build_method_mapping())


def get_strategy_method_ids(strat_id):
    """Returns the method ID imnplementing the selection strategy.

    Transform strategy keyword into its ID and resolves aliases.
    """
    if strat_id not in STRATEGIES:
        raise ValueError(f"Unknown {strat_id} strategy.")
    return STRATEGY_METHOD_IDS[strat_id]
