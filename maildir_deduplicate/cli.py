# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2016 Kevin Deldycke <kevin@deldycke.com>
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

import email
import os
import re

import click
import click_log

from . import (
    DEFAULT_DIFF_THRESHOLD,
    DEFAULT_SIZE_DIFFERENCE_THRESHOLD,
    DELETE_MATCHING_PATH,
    DELETE_NEWER,
    DELETE_NEWEST,
    DELETE_NON_MATCHING_PATH,
    DELETE_OLDER,
    DELETE_OLDEST,
    MD_SUBDIRS,
    STRATEGIES,
    TIME_SOURCES,
    __version__,
    logger
)
from .deduplicate import Deduplicate


@click.group(invoke_without_command=True)
@click_log.init(logger)
@click_log.simple_verbosity_option(default='INFO', metavar='LEVEL')
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """ CLI for maildirs content analysis and deletion. """
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
    '--strategy', type=click.Choice(STRATEGIES),
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
    '-s', '--show-diffs', count=True,
    help='Show diffs between duplicates even if they are within the '
    'thresholds.')
@click.option(
    '-i', '--message-id', is_flag=True, default=False,
    help='Use Message-ID header as hash key. This is not recommended: the '
    'default is to compute a digest of the whole header with selected '
    'headers removed.')
@click.option(
    '-S', '--size-threshold', type=int, metavar='BYTES',
    default=DEFAULT_SIZE_DIFFERENCE_THRESHOLD,
    help='Specify maximum allowed difference between size of duplicates. Set '
    'to -1 for no threshold. Defaults to {}.'.format(
        DEFAULT_SIZE_DIFFERENCE_THRESHOLD))
@click.option(
    '-D', '--diff-threshold', type=int, metavar='BYTES',
    default=DEFAULT_DIFF_THRESHOLD,
    help='Specify maximum allowed difference between size of duplicates. Set '
    'to -1 for no threshold. Defaults to {}.'.format(DEFAULT_DIFF_THRESHOLD))
@click.argument(
    'maildirs', nargs=-1, callback=validate_maildirs,
    type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.pass_context
def deduplicate(
        ctx, strategy, time_source, regexp, dry_run, show_diffs, message_id,
        size_threshold, diff_threshold, maildirs):
    """ Deduplicate mails from a set of maildir folders.

    \b
    Removal strategies for subsets of duplicate mails sharing the same hash:
        - delete-older:    Deletes the olders,    keeps the newests.
        - delete-oldest:   Deletes the oldests,   keeps the newers.
        - delete-newer:    Deletes the newers,    keeps the oldests.
        - delete-newest:   Deletes the newests,   keeps the olders.
        - delete-smaller:  Deletes the smallers,  keeps the biggests.
        - delete-smallest: Deletes the smallests, keeps the biggers.
        - delete-bigger:   Deletes the biggers,   keeps the smallests.
        - delete-biggest:  Deletes the biggests,  keeps the smallers.
        - delete-matching-path: Deletes all duplicates whose file path match
        the regular expression provided via the --regexp parameter.
        - delete-non-matching-path: Deletes all duplicates whose file path
        doesn't match the regular expression provided via the --regexp
        parameter.
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

    dedup = Deduplicate(
        strategy, time_source, regexp, dry_run, show_diffs, message_id,
        size_threshold, diff_threshold)
    for maildir in maildirs:
        dedup.add_maildir(maildir)
    dedup.run()
    dedup.report()


@cli.command(short_help='Hash a single mail.')
@click.option(
    '-i', '--message-id', is_flag=True, default=False,
    help='Use Message-ID header as hash key. This is not recommended: the '
    'default is to compute a digest of the whole header with selected headers '
    'removed.')
@click.argument('message', type=click.File('r'))
@click.pass_context
def hash(ctx, message_id, message):
    """ Take a single mail message and show its canonicalised form and hash.

    This is essentially provided for debugging why two messages do not have the
    same hash when you expect them to (or vice-versa).

    \b
    To get the message from STDIN, use a dash in place of the filename:
        cat mail.txt | mdedup hash -
    """
    message = email.message_from_file(message)
    mail_hash, header_text = Deduplicate.compute_hash(
        None, message, message_id)
    logger.info(header_text)
    logger.info('_______________________________________')
    logger.info('Hash: {}'.format(mail_hash))
