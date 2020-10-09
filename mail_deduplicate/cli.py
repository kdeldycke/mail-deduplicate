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
from functools import partial

import click
import click_log
from click_help_colors import HelpColorsCommand, HelpColorsGroup, version_option

from . import (
    CLI_NAME,
    DATE_HEADER,
    DEFAULT_CONTENT_THRESHOLD,
    DEFAULT_SIZE_THRESHOLD,
    DISCARD_MATCHING_PATH,
    DISCARD_NON_MATCHING_PATH,
    HASH_HEADERS,
    STRATEGIES,
    TIME_SOURCES,
    Config,
    __version__,
    env_data,
    logger,
)
from .deduplicate import Deduplicate
from .mailbox import BOX_TYPES

click_log.basic_config(logger)


def collect_keywords(ctx):
    """ Parse click context to collect option names and choice keywords. """
    options = set()
    choices = set()
    metavars = set()

    # Add user defined help options.
    options.update(ctx.help_option_names)

    # Collect all option names and choice keywords.
    for param in ctx.command.params:
        options.update(param.opts)
        if isinstance(param.type, click.Choice):
            choices.update(param.type.choices)
        if param.metavar:
            metavars.add(param.metavar)

    return options, choices, metavars


def colorized_help(ctx):
    """Get default help screen and colorize section titles, options and choice
    keywords."""
    cli_color = "white"
    title_color = "yellow"
    option_color = "green"
    choice_color = "blue"
    metavar_color = "bright_black"

    options, choices, metavars = collect_keywords(ctx)

    help_txt = ctx.get_help()

    def colorize(match, fg=None):
        """Re-create the matching string by concatenating all groups, but only
        colorize named groups.
        """
        txt = ""
        for group in match.groups():
            if group in match.groupdict().values():
                txt += click.style(group, fg=fg)
            else:
                txt += group
        return txt

    # Highligh numbers.
    help_txt = re.sub(
        r"(\s)(?P<colorize>-?\d+)", partial(colorize, fg=choice_color), help_txt
    )

    # Highlight CLI.
    help_txt = re.sub(
        fr"(\s)(?P<colorize>{CLI_NAME})", partial(colorize, fg=cli_color), help_txt
    )

    # Highligh sections.
    help_txt = re.sub(
        r"^(?P<colorize>\S[\S+ ]+)(:)",
        partial(colorize, fg=title_color),
        help_txt,
        flags=re.MULTILINE,
    )

    # Highlight keywords.
    for keywords, color in [
        (sorted(options), option_color),
        (sorted(choices, reverse=True), choice_color),
        (sorted(metavars, reverse=True), metavar_color),
    ]:
        for keyword in keywords:
            # Accounts for text wrapping after a dash.
            keyword = keyword.replace("-", "-\s*")
            help_txt = re.sub(
                fr"([\s\[\|])(?P<colorize>{keyword})",
                partial(colorize, fg=color),
                help_txt,
            )

    return help_txt


def validate_regexp(ctx, param, value):
    """ Validate and compile regular expression. """
    if value:
        try:
            value = re.compile(value)
        except ValueError:
            raise click.BadParameter("invalid regular expression.")
    return value


@click.command(
    short_help="Deduplicate mail boxes content.",
    no_args_is_help=False,
)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    default=False,
    help="Do not actually performs anything; just apply the selection strategy, and "
    "show which action would have been performed otherwise.",
)
@click.option(
    "-i",
    "--input-format",
    type=click.Choice(sorted(BOX_TYPES), case_sensitive=False),
    help="Force all provided mail sources to be parsed in the specified format. If "
    "not set, auto-detect the format of sources independently. Auto-detection only "
    "supports maildir and mbox format. So use this option to open up other box "
    "format, or bypass unreliable detection.",
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
    help="Headers to use to compute each mail's hash. Must be repeated multiple times "
    "to set an ordered list of headers. Header IDs are case-insensitive. Repeating "
    "entries are removed. Defaults to: {}.".format(
        " ".join([f"-h {h}" for h in HASH_HEADERS])
    ),
)
@click.option(
    "-S",
    "--size-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_SIZE_THRESHOLD,
    help="Maximum difference allowed in size between mails sharing the same hash. "
    "The whole subset of duplicates will be rejected if at least one pair of mail "
    "exceed the threshold. Set to 0 to enforce strictness and deduplicate the subset "
    "only if all mails are exactly the same. Set to -1 to allow any difference and "
    "keep deduplicating the subset whatever the differences. Defaults to "
    f"{DEFAULT_SIZE_THRESHOLD} bytes.",
)
@click.option(
    "-C",
    "--content-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_CONTENT_THRESHOLD,
    help="Maximum difference allowed in content between mails sharing the same hash. "
    "The whole subset of duplicates will be rejected if at least one pair of mail "
    "exceed the threshold. Set to 0 to enforce strictness and deduplicate the subset "
    "only if all mails are exactly the same. Set to -1 to allow any difference and "
    "keep deduplicating the subset whatever the differences. Defaults to "
    f"{DEFAULT_CONTENT_THRESHOLD} bytes.",
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
    help="Selection strategy to apply within a subset of duplicates. If not set, "
    "duplicates will be grouped and counted but no selection will happen, and no "
    "action will be performed on the set.",
)
@click.option(
    "-t",
    "--time-source",
    default=DATE_HEADER,
    type=click.Choice(sorted(TIME_SOURCES), case_sensitive=False),
    help="Source of a mail's time reference used in time-sensitive strategies. "
    f"Defaults to {DATE_HEADER}.",
)
@click.option(
    "-r",
    "--regexp",
    callback=validate_regexp,
    metavar="REGEXP",
    help="Regular expression against a mail file path. Required in "
    "discard-matching-path and discard-non-matching-path strategies.",
)
@click.argument(
    "mail_sources",
    nargs=-1,
    metavar="MAIL_SOURCE_1 MAIL_SOURCE_2 ...",
    type=click.Path(exists=True, resolve_path=True),
)
@click_log.simple_verbosity_option(
    logger,
    default="INFO",
    metavar="LEVEL",
    type=click.Choice(
        ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False
    ),
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG. Defaults to INFO.",
)
@version_option(
    version=__version__,
    prog_name=CLI_NAME,
    version_color="green",
    prog_name_color="white",
    message=f"%(prog)s %(version)s\n{env_data}",
    message_color="bright_black",
)
@click.pass_context
def mdedup(
    ctx,
    dry_run,
    input_format,
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
    """Deduplicate mails from a set of mail boxes.

    \b
    Process:
    * Phase #1: run a first pass to compute from their headers the canonical hash of
                each encountered mail.
    * Phase #2: a second pass to apply the selection strategy on each subset of
                duplicate mails sharing the same hash.
    * Phase #3: perform an action on all selected mails.

    A dozen of strategies are available to select mails in each subset:

    \b
    Time-based:
    * discard-older:    Discards the olders,    keeps the newests.
    * discard-oldest:   Discards the oldests,   keeps the newers.
    * discard-newer:    Discards the newers,    keeps the oldests.
    * discard-newest:   Discards the newests,   keeps the olders.

    \b
    Size-based:
    * discard-smaller:  Discards the smallers,  keeps the biggests.
    * discard-smallest: Discards the smallests, keeps the biggers.
    * discard-bigger:   Discards the biggers,   keeps the smallests.
    * discard-biggest:  Discards the biggests,  keeps the smallers.

    \b
    File-based:
    * discard-matching-path: Discardss all duplicates whose file path match the
    regular expression provided via the --regexp parameter.
    * discard-non-matching-path: Discardss all duplicates whose file path
    doesn't match the regular expression provided via the --regexp parameter.

    Action on the selected mails in phase #3 is only performed if no major differences
    between mails are uncovered during a fine-grained check differences in the second
    phase. Limits can be set via the --size-threshold and --content-threshold options.
    """
    level = logger.level
    level_name = logging._levelToName.get(level, level)
    logger.debug(f"Verbosity set to {level_name}.")

    # Print help screen and exit if no mail source provided.
    if not mail_sources:
        # Apply dynamic style to help screen.
        click.echo(colorized_help(ctx))
        ctx.exit()

    # Validate exclusive options requirement depending on strategy.
    requirements = [
        (regexp, "-r/--regexp", {DISCARD_MATCHING_PATH, DISCARD_NON_MATCHING_PATH}),
    ]
    for param_value, param_name, required_strategies in requirements:
        if strategy in required_strategies:
            if not param_value:
                raise click.BadParameter(
                    f"{strategy} strategy requires the {param_name} parameter."
                )
        elif param_value:
            raise click.BadParameter(
                f"{param_name} parameter not allowed in {strategy} strategy."
            )

    conf = Config(
        dry_run=dry_run,
        input_format=input_format,
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

    click.echo(click.style("\n● Phase #0 - Load mails", fg="blue", bold=True))
    for source in mail_sources:
        dedup.add_source(source)

    click.echo(
        click.style(
            "\n● Phase #1 - Compute hashes and group duplicates", fg="blue", bold=True
        )
    )
    dedup.hash_all()
    if hash_only:
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                click.echo(mail.pretty_headers)
                click.echo(f"Hash: {mail.hash_key}")
        ctx.exit()

    click.echo(
        click.style("\n● Phase #2 - Select candidates in groups", fg="blue", bold=True)
    )
    dedup.gather_candidates()

    click.echo(
        click.style(
            "\n● Phase #3 - Perform action on all candidates", fg="blue", bold=True
        )
    )
    dedup.remove_duplicates()

    click.echo(
        click.style("\n● Phase #4 - Report and statistics", fg="blue", bold=True)
    )
    # Print deduplication statistics, then performs a self-check on them.
    click.echo(dedup.report())
    dedup.check_stats()
