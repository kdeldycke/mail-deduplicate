# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Kevin Deldycke <kevin@deldycke.com>
#                         Adam Spiers <adam@spiers.net>
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

from __future__ import (
    division, print_function, absolute_import
)

import email
import re
import os

import click

from . import (
    __version__, STRATEGIES, MATCHING, NOT_MATCHING,
    DEFAULT_SIZE_DIFFERENCE_THRESHOLD, DEFAULT_DIFF_THRESHOLD,
    Deduplicate
)


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.option('-v', '--verbose', is_flag=True, default=False,
              help='Print much more debug statements.')
@click.pass_context
def cli(ctx, verbose):
    """ CLI for maildirs content analysis and deletion. """
    # Print help screen and exit if no sub-commands provided.
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit()
    # Load up global options to the context.
    ctx.obj = {
        'verbose': verbose}


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
        for subdir in ('cur', 'new', 'tmp'):
            if not os.path.isdir(os.path.join(path, subdir)):
                raise click.BadParameter(
                    '{} is not a maildir (missing {!r} sub-directory).'.format(
                        path, subdir))
    return value


@cli.command(short_help='Deduplicate maildirs content.')
@click.option('--strategy', type=click.Choice(STRATEGIES),
              help='Removal strategy to apply on found duplicates.')
@click.option('-r', '--regexp', callback=validate_regexp, metavar='REGEXP',
              help='Regular expression for file path. Required in matching and '
              'not-matching strategies.')
@click.option('-n', '--dry-run', is_flag=True, default=False,
              help='Do not actually remove anything; just show what would be '
              'removed.')
@click.option('-s', '--show-diffs', count=True,
              help='Show diffs between duplicates even if they are within the '
              'thresholds.')
@click.option('-i', '--message-id', is_flag=True, default=False,
              help='Use Message-ID header as hash key. This is not '
              'recommended: the default is to compute a digest of the whole '
              'header with selected headers removed.')
@click.option('-S', '--size-threshold', type=int, metavar='BYTES',
              default=DEFAULT_SIZE_DIFFERENCE_THRESHOLD,
              help='Specify maximum allowed difference between size of '
              'duplicates. Set to -1 for no threshold. Defaults to {}.'.format(
                DEFAULT_SIZE_DIFFERENCE_THRESHOLD))
@click.option('-D', '--diff-threshold', type=int, metavar='BYTES',
              default=DEFAULT_DIFF_THRESHOLD,
              help='Specify maximum allowed difference between size of '
              'duplicates. Set to -1 for no threshold. Defaults to {}.'.format(
                DEFAULT_DIFF_THRESHOLD))
@click.argument('maildirs', type=click.Path(exists=True, file_okay=False,
                                            resolve_path=True), nargs=-1,
                callback=validate_maildirs)
@click.pass_context
def deduplicate(ctx, strategy, regexp, dry_run, show_diffs, message_id,
                size_threshold, diff_threshold, maildirs):
    """ Deduplicate mails from a set of maildir folders.

    \b
    Removal strategies for each set of mail duplicates:
        - older: remove all but the newest message (determined by ctime).
        - newer: remove all but the oldest message (determined by ctime).
        - smaller: Remove all but largest message.
        - matching: Remove duplicates whose file path matches the regular
          expression provided via the --regexp parameter.
        - not-matching: Remove duplicates whose file path does not match the
          regular expression provided via the --regexp parameter.
    """
    # Print help screen and exit if no maildir folder provided.
    if not maildirs:
        click.echo(ctx.get_help())
        ctx.exit()

    # Validate options requirement depending on strategy.
    if strategy in [MATCHING, NOT_MATCHING]:
        if not regexp:
            raise click.BadParameter(
                '{} strategy requires the --regexp parameter.'.format(
                    strategy))
    elif regexp:
        raise click.BadParameter(
            '--regexp parameter not allowed in {} strategy.'.format(strategy))

    dedup = Deduplicate(
        strategy, regexp, dry_run, show_diffs, message_id,
        size_threshold, diff_threshold)
    for maildir in maildirs:
        dedup.add_maildir(maildir)
    dedup.run()
    dedup.report()


@cli.command(short_help='Hash a single mail.')
@click.option('-i', '--message-id', is_flag=True, default=False,
              help='Use Message-ID header as hash key. This is not '
              'recommended: the default is to compute a digest of the whole '
              'header with selected headers removed.')
@click.argument('message', type=click.File('rb'))
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
    click.echo(header_text)
    click.echo('_______________________________________')
    click.echo('Hash: {}'.format(mail_hash))
