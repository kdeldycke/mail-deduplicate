# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2017 Kevin Deldycke <kevin@deldycke.com>
#                         and contributors.
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

from __future__ import absolute_import, division, print_function

import logging
import os
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
    MD_SUBDIRS,
    STRATEGIES,
    TIME_SOURCES,
    Config,
    __version__,
)
from .deduplicate import Deduplicate
from .mail import Mail


cli_logger = logging.getLogger(__name__)
logger = click_log.basic_config('mdedup')
@click.group(invoke_without_command=True)
@click_log.simple_verbosity_option(
    'mdedup',
    default='INFO', metavar='LEVEL',
    help='Either CRITICAL, ERROR, WARNING, INFO or DEBUG. Defaults to INFO.')
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """ CLI for maildirs content analysis and deletion. """
    level = logging.getLogger('mdedup').level
    try:
        level_to_name = logging._levelToName
    # Fallback to pre-Python 3.4 internals.
    except AttributeError:
        level_to_name = logging._levelNames
    level_name = level_to_name.get(level, level)
    logger.debug('Verbosity set to {}.'.format(level_name))

    # Print help screen and exit if no sub-commands provided.
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit()

    # Load up global options to the context.
    ctx.obj = {}


def validate_regexp(ctx, param, value):
    """ Validate and compile regular expression. """
    if value:
        try:
            value = re.compile(value)
        except ValueError:
            raise click.BadParameter('invalid regular expression.')
    return value


def validate_maildirs(ctx, param, value):
    """ Check that folders are maildirs. """
    for path in value:
        for subdir in MD_SUBDIRS:
            if not os.path.isdir(os.path.join(path, subdir)):
                raise click.BadParameter(
                    '{} is not a maildir (missing {!r} sub-directory).'.format(
                        path, subdir))
    return value


@cli.command(short_help='Deduplicate maildirs content.')
@click.option(
    '-s', '--strategy', type=click.Choice(STRATEGIES), required=True,
    help='Deletion strategy to apply within a subset of duplicates.')
@click.option(
    '-t', '--time-source', type=click.Choice(TIME_SOURCES),
    help="Source of a mail's reference time. Required in time-sensitive "
    'strategies.')
@click.option(
    '-r', '--regexp', callback=validate_regexp, metavar='REGEXP',
    help='Regular expression against a mail file path. Required in '
    'delete-matching-path and delete-non-matching-path strategies.')
@click.option(
    '-n', '--dry-run', is_flag=True, default=False,
    help='Do not actually delete anything; just show what would be removed.')
@click.option(
    '-i', '--message-id', is_flag=True, default=False,
    help='Only use the Message-ID header as a hash key. Not recommended. '
    'Replace the default behavior consisting in deriving the hash from '
    'several headers.')
@click.option(
    '-S', '--size-threshold', type=int, metavar='BYTES',
    default=DEFAULT_SIZE_THRESHOLD,
    help='Maximum allowed difference in size between mails. Whole subset of '
    'duplicates will be rejected above threshold. Set to -1 to not allow any '
    'difference. Defaults to {} bytes.'.format(DEFAULT_SIZE_THRESHOLD))
@click.option(
    '-C', '--content-threshold', type=int, metavar='BYTES',
    default=DEFAULT_CONTENT_THRESHOLD,
    help='Maximum allowed difference in content between mails. Whole subset '
    'of duplicates will be rejected above threshold. Set to -1 to not allow '
    'any difference. Defaults to {} bytes.'.format(DEFAULT_CONTENT_THRESHOLD))
@click.option(
    '-d', '--show-diff', is_flag=True, default=False,
    help='Show the unified diff of duplicates not within thresholds.')
# TODO: add a show-progress option.
@click.argument(
    'maildirs', nargs=-1, callback=validate_maildirs,
    type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.pass_context
def deduplicate(
        ctx, strategy, time_source, regexp, dry_run, message_id,
        size_threshold, content_threshold, show_diff, maildirs):
    """ Deduplicate mails from a set of maildir folders.

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
    the second pass. Limits can be set via the threshold options.
    """
    # Print help screen and exit if no maildir folder provided.
    if not maildirs:
        click.echo(ctx.get_help())
        ctx.exit()

    # Validate exclusive options requirement depending on strategy.
    requirements = [
        (time_source, '-t/--time-source', [
            DELETE_OLDER, DELETE_OLDEST, DELETE_NEWER, DELETE_NEWEST]),
        (regexp, '-r/--regexp', [
            DELETE_MATCHING_PATH, DELETE_NON_MATCHING_PATH])]
    for param_value, param_name, required_strategies in requirements:
        if strategy in required_strategies:
            if not param_value:
                raise click.BadParameter(
                    '{} strategy requires the {} parameter.'.format(
                        strategy, param_name))
        elif param_value:
            raise click.BadParameter(
                '{} parameter not allowed in {} strategy.'.format(
                    param_name, strategy))

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

    logger.info('=== Start phase #1: load mails and compute hashes.')
    for maildir in maildirs:
        dedup.add_maildir(maildir)

    logger.info('=== Start phase #2: deduplicate mails.')
    dedup.run()

    dedup.report()


@cli.command(short_help='Hash a single mail.')
# TODO: Deduplicate option definition.
@click.option(
    '-i', '--message-id', is_flag=True, default=False,
    help='Only use the Message-ID header as a hash key. Not recommended. '
    'Replace the default behavior consisting in deriving the hash from '
    'several headers.')
@click.argument('message', type=click.Path(
    exists=True, dir_okay=False, resolve_path=True))
@click.pass_context
def hash(ctx, message_id, message):
    """ Take a single mail message and show its canonicalised form and hash.

    Mainly used to debug message hashing.
    """
    conf = Config(message_id=message_id)

    mail = Mail(message, conf)

    logger.info(mail.header_text)
    logger.info('-' * 70)
    logger.info('Hash: {}'.format(mail.hash_key))
