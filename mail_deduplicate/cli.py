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
    HASH_HEADERS,
    STRATEGIES,
    TIME_SOURCES,
    Config,
    __version__,
    logger,
)
from .mailbox import BOX_TYPES
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
    "-f",
    "--sources-format",
    type=click.Choice(sorted(BOX_TYPES), case_sensitive=False),
    help="Force all provided mail sources to be parsed in the specified format. "
    "If not set, auto-detect the format of sources independently. Because "
    "auto-detection only supports 'maildir' and 'mbox' format, this option is "
    "helpful to open rare kind of mail sources.",
)
@click.option(
    "-u",
    "--force-unlock",
    is_flag=True,
    default=False,
    help="Remove the lock on mail source opening if one is found.",
)
@click.option(
    "-H",
    "--hash-only",
    is_flag=True,
    default=False,
    help="Compute and display the internal hashes used to identify duplicates. Do not "
    "performs any deduplication operation.",
)
@click.option(
    "-h",
    "--hash-header",
    multiple=True,
    type=str,
    metavar="Header-ID",
    default=HASH_HEADERS,
    help="Headers to use to compute each mail's hash. Must be repeated multiple "
    "times to set an ordered list of headers. IDs are case-insensitive. Duplicate "
    'entries are removed. Defaults to: "{}".'.format(
        " ".join(["-h {}".format(h) for h in HASH_HEADERS])
    ),
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
    type=click.Choice(sorted(STRATEGIES), case_sensitive=False),
    help="Deletion strategy to apply within a subset of duplicates. If not set, "
    "duplicates will be grouped and counted but no removal will happens.",
)
@click.option(
    "-t",
    "--time-source",
    type=click.Choice(sorted(TIME_SOURCES), case_sensitive=False),
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
@click.argument(
    "mail_sources",
    nargs=-1,
    metavar="MAIL_SOURCE_1 MAIL_SOURCE_2 (...)",
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
    sources_format,
    force_unlock,
    hash_only,
    hash_header,
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
    between mails are uncovered during a fine-grained check differences in the
    second phase. Limits can be set via the --size-threshold and --content-threshold
    options.
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
            {DELETE_OLDER, DELETE_OLDEST, DELETE_NEWER, DELETE_NEWEST},
        ),
        (regexp, "-r/--regexp", {DELETE_MATCHING_PATH, DELETE_NON_MATCHING_PATH}),
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
        dry_run=dry_run,
        sources_format=sources_format,
        force_unlock=force_unlock,
        hash_only=hash_only,
        hash_headers=hash_header,
        size_threshold=size_threshold,
        content_threshold=content_threshold,
        show_diff=show_diff,
        strategy=strategy,
        time_source=time_source,
        regexp=regexp,
    )

    dedup = Deduplicate(conf)

    click.echo(click.style("\n● Phase #1 - Load mails", fg="blue", bold=True))
    for source in mail_sources:
        dedup.add_source(source)

    click.echo(click.style("\n● Phase #2 - Compute hashes", fg="blue", bold=True))
    dedup.hash_all()
    if hash_only:
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                click.echo(mail.pretty_headers)
                click.echo("Hash: {}".format(mail.hash_key))
        ctx.exit()

    click.echo(click.style("\n● Phase #3 - Detect duplicates", fg="blue", bold=True))
    dedup.gather_candidates()

    click.echo(click.style("\n● Phase #4 - Delete candidates", fg="blue", bold=True))
    dedup.remove_duplicates()

    click.echo(click.style("\n● Phase #5 - Report", fg="blue", bold=True))
    # Print deduplication statistics, then performs a self-check on them.
    click.echo(dedup.report())
    dedup.check_stats()
