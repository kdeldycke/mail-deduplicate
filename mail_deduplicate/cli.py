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

import logging
import re
from pathlib import Path

import click
import click_log

from . import (
    DEFAULT_CONTENT_THRESHOLD,
    DEFAULT_SIZE_THRESHOLD,
    DELETE_MATCHING_PATH,
    DELETE_NEWER,
    DELETE_NEWEST,
    DELETE_NON_MATCHING_PATH,
    DELETE_OLDER,
    DELETE_OLDEST,
    STRATEGIES,
    TIME_SOURCES,
    Config,
    __version__,
    logger,
)
from .deduplicate import Deduplicate

click_log.basic_config(logger)


def validate_regexp(ctx, param, value):
    """ Validate and compile regular expression. """
    if value:
        try:
            value = re.compile(value)
        except ValueError:
            raise click.BadParameter("invalid regular expression.")
    return value


@click.command(short_help="Deduplicate mail boxes content.", no_args_is_help=True)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    default=False,
    help="Do not actually delete anything; just show which mails would be removed.",
)
@click.option(
    "-h",
    "--hash-only",
    is_flag=True,
    default=False,
    help="Compute and display the internal hashes used to identify duplicates. Do not "
    "performs any deduplication operation.",
)
@click.option(
    "-i",
    "--message-id",
    is_flag=True,
    default=False,
    help="Only use the Message-ID header as a hash key. Not recommended. Replace the "
    "default behavior consisting in deriving the hash from several headers.",
)
@click.option(
    "-S",
    "--size-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_SIZE_THRESHOLD,
    help="Maximum difference allowed in size between mails sharing the same hash. "
    "The whole subset of duplicates will be rejected for deduplication if any of two "
    "mails deviates above the threshold. Set to 0 to get strict and deduplicate the "
    "subset only if all mails are exactly the same. Set to -1 to allow "
    "any difference and keep deduplicating the subset whatever the differences. "
    "Defaults to {} bytes.".format(DEFAULT_SIZE_THRESHOLD),
)
@click.option(
    "-C",
    "--content-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_CONTENT_THRESHOLD,
    help="Maximum difference allowed in content between mails sharing the same hash. "
    "The whole subset of duplicates will be rejected for deduplication if any of two "
    "mails deviates above the threshold. Set to 0 to get strict and deduplicate the "
    "subset only if all mails are exactly the same. Set to -1 to allow "
    "any difference and keep deduplicating the subset whatever the differences. "
    "Defaults to {} bytes.".format(DEFAULT_CONTENT_THRESHOLD),
)
@click.option(
    "-d",
    "--show-diff",
    is_flag=True,
    default=False,
    help="Show the unified diff of duplicates not within thresholds.",
)
@click.option(
    "-s",
    "--strategy",
    type=click.Choice(STRATEGIES),
    help="Deletion strategy to apply within a subset of duplicates. If not set, "
    "duplicates will be grouped and counted but no removal will happens.",
)
@click.option(
    "-t",
    "--time-source",
    type=click.Choice(TIME_SOURCES),
    help="Source of a mail's time reference. Required in time-sensitive strategies.",
)
@click.option(
    "-r",
    "--regexp",
    callback=validate_regexp,
    metavar="REGEXP",
    help="Regular expression against a mail file path. Required in "
    "delete-matching-path and delete-non-matching-path strategies.",
)
# New option:
# show their canonicalised forms of mails
# TODO: add a show-progress option.
@click.argument(
    "mail_sources",
    nargs=-1,
    metavar="MBOXES/MAILDIRS",
    type=click.Path(exists=True, resolve_path=True),
)
@click_log.simple_verbosity_option(
    logger,
    default="INFO",
    metavar="LEVEL",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG. Defaults to INFO.",
)
@click.version_option(__version__)
@click.pass_context
def mdedup(
    ctx,
    dry_run,
    hash_only,
    message_id,
    size_threshold,
    content_threshold,
    show_diff,
    strategy,
    time_source,
    regexp,
    mail_sources,
):
    """Deduplicate mails from a set of either mbox files or maildir folders.

    Run a first pass computing the canonical hash of each encountered mail from
    their headers, then a second pass to apply the deletion strategy on each
    subset of duplicate mails.

    \b
    Removal strategies for each subsets of duplicate mails:
      - delete-older:    Deletes the olders,    keeps the newests.
      - delete-oldest:   Deletes the oldests,   keeps the newers.
      - delete-newer:    Deletes the newers,    keeps the oldests.
      - delete-newest:   Deletes the newests,   keeps the olders.
      - delete-smaller:  Deletes the smallers,  keeps the biggests.
      - delete-smallest: Deletes the smallests, keeps the biggers.
      - delete-bigger:   Deletes the biggers,   keeps the smallests.
      - delete-biggest:  Deletes the biggests,  keeps the smallers.
      - delete-matching-path: Deletes all duplicates whose file path match the
      regular expression provided via the --regexp parameter.
      - delete-non-matching-path: Deletes all duplicates whose file path
      doesn't match the regular expression provided via the --regexp parameter.

    Deletion strategy on a duplicate set only applies if no major differences
    between mails are uncovered during a fine-grained check differences during
    the second pass. Limits can be set via the --size-threshold and
    --content-threshold options.
    """
    level = logger.level
    level_name = logging._levelToName.get(level, level)
    logger.debug(f"Verbosity set to {level_name}.")

    # Print help screen and exit if no mail source provided.
    if not mail_sources:
        click.echo(ctx.get_help())
        ctx.exit()

    # Validate exclusive options requirement depending on strategy.
    requirements = [
        (
            time_source,
            "-t/--time-source",
            [DELETE_OLDER, DELETE_OLDEST, DELETE_NEWER, DELETE_NEWEST],
        ),
        (regexp, "-r/--regexp", [DELETE_MATCHING_PATH, DELETE_NON_MATCHING_PATH]),
    ]
    for param_value, param_name, required_strategies in requirements:
        if strategy in required_strategies:
            if not param_value:
                raise click.BadParameter(
                    "{} strategy requires the {} parameter.".format(
                        strategy, param_name
                    )
                )
        elif param_value:
            raise click.BadParameter(
                "{} parameter not allowed in {} strategy.".format(param_name, strategy)
            )

    conf = Config(
        strategy=strategy,
        time_source=time_source,
        regexp=regexp,
        dry_run=dry_run,
        show_diff=show_diff,
        message_id=message_id,
        size_threshold=size_threshold,
        content_threshold=content_threshold,
        # progress=progress,
    )

    dedup = Deduplicate(conf)

    click.echo("=== Phase #1: load mails.")
    for source in mail_sources:
        dedup.add_source(source)

    click.echo("=== Phase #2: compute mail hashes.")
    dedup.hash_all()
    if hash_only:
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                click.echo(mail.header_text)
                click.echo("-" * 70)
                click.echo("Hash: {}".format(mail.hash_key))
        ctx.exit()

    click.echo("=== Phase #3: detect duplicates.")
    dedup.gather_candidates()

    click.echo("=== Phase #4: remove candidates.")
    dedup.remove_duplicates()

    click.echo("=== Phase #5: statistics and self-checks.")
    # Print deduplication statistics, then performs a self-check on them.
    click.echo(dedup.report())
    dedup.check_stats()
