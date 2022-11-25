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

from __future__ import annotations

import re

from click_extra import BadParameter, Choice
from click_extra import Path as ClickPath
from click_extra import argument, echo, extra_command, option, pass_context, progressbar
from click_extra.colorize import default_theme as theme
from click_extra.commands import ExtraCommand

from . import (
    DATE_HEADER,
    DEFAULT_CONTENT_THRESHOLD,
    DEFAULT_SIZE_THRESHOLD,
    HASH_HEADERS,
    TIME_SOURCES,
    Config,
    __version__,
)
from .action import (
    ACTIONS,
    COPY_DISCARDED,
    COPY_SELECTED,
    MOVE_DISCARDED,
    MOVE_SELECTED,
    perform_action,
)
from .deduplicate import (
    BODY_HASHER_NORMALIZED,
    BODY_HASHER_RAW,
    BODY_HASHER_SKIP,
    BODY_HASHERS,
    Deduplicate,
)
from .mailbox import BOX_STRUCTURES, BOX_TYPES
from .strategy import (
    DISCARD_MATCHING_PATH,
    DISCARD_NON_MATCHING_PATH,
    SELECT_MATCHING_PATH,
    SELECT_NON_MATCHING_PATH,
    STRATEGY_METHODS,
)


def validate_regexp(ctx, param, value):
    """Validate and compile regular expression."""
    if value:
        try:
            value = re.compile(value)
        except ValueError:
            raise BadParameter("invalid regular expression.")
    return value


class MdedupCommand(ExtraCommand):
    def format_help(self, ctx, formatter):
        """Feed our custom formatter instance with the keywords to highlight."""
        # Populate the formatter with the default help screen content.
        super().format_help(ctx, formatter)

        # Produce the strategy reference table, with grouped aliases.
        method_to_ids = {}
        for strat_id, method in sorted(STRATEGY_METHODS.items(), reverse=True):
            method_to_ids.setdefault(method, []).append(strat_id)
        strat_table = sorted(
            [
                (f"[{'|'.join(strat_ids)}]", " ".join(method.__doc__.split()))
                for method, strat_ids in method_to_ids.items()
            ]
        )

        # Extend the default help screen by adding our strategy as an epilog.
        with formatter.section("Available strategies"):
            formatter.write_dl(strat_table)


@extra_command(
    cls=MdedupCommand,
    version=__version__,
    short_help="Deduplicate mail boxes.",
    # Force linear layout for definition lists. See:
    # https://cloup.readthedocs.io/en/stable/pages/formatting.html#the-linear-layout-for-definition-lists
    formatter_settings={"col2_min_width": 9999999999},
)
@option(
    "-n",
    "--dry-run",
    is_flag=True,
    default=False,
    help="Do not perform any action but act as if it was, and report which action "
    "would have been performed otherwise.",
)
@option(
    "-i",
    "--input-format",
    type=Choice(sorted(BOX_TYPES), case_sensitive=False),
    help="Force all provided mail sources to be parsed in the specified format. If "
    "not set, auto-detect the format of sources independently. Auto-detection only "
    "supports maildir and mbox format. Use this option to open up other box "
    "format, or bypass unreliable detection.",
)
@option(
    "-u",
    "--force-unlock",
    is_flag=True,
    default=False,
    help="Remove the lock on mail source opening if one is found.",
)
@option(
    "-H",
    "--hash-only",
    is_flag=True,
    default=False,
    help="Compute and display the internal hashes used to identify duplicates. Do not "
    "performs any selection or action.",
)
@option(
    "-h",
    "--hash-header",
    multiple=True,
    type=str,
    metavar="Header-ID",
    default=HASH_HEADERS,
    help="Headers to use to compute each mail's hash. Must be repeated multiple times "
    "to set an ordered list of headers. Header IDs are case-insensitive. Repeating "
    "entries are ignored.",
)
@option(
    "-b",
    "--hash-body",
    default=BODY_HASHER_SKIP,
    type=Choice(sorted(BODY_HASHERS), case_sensitive=False),
    help="Body hash to use to compute each mail's hash. Defaults to "
    f"{BODY_HASHER_SKIP} as it is the fastest: it will not compute the body hash and "
    f"header hash should be sufficient to determine duplicate set. {BODY_HASHER_RAW} use the "
    "body as it is: keeping line breaks and spaces to compute the body hash. "
    f"{BODY_HASHER_NORMALIZED} use a cleaned body: remove all line breaks and spaces "
    "before computing body hash (slowest).",
)
@option(
    "-S",
    "--size-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_SIZE_THRESHOLD,
    help="Maximum difference allowed in size between mails sharing the same hash. "
    "The whole subset of duplicates will be skipped if at least one pair of mail "
    "exceeds the threshold. Set to 0 to enforce strictness and apply selection strategy "
    "on the subset only if all mails are exactly the same. Set to -1 to allow any "
    "difference and apply the strategy whatever the differences.",
)
@option(
    "-C",
    "--content-threshold",
    type=int,
    metavar="BYTES",
    default=DEFAULT_CONTENT_THRESHOLD,
    help="Maximum difference allowed in content between mails sharing the same hash. "
    "The whole subset of duplicates will be skipped if at least one pair of mail "
    "exceeds the threshold. Set to 0 to enforce strictness and apply selection strategy "
    "on the subset only if all mails are exactly the same. Set to -1 to allow any "
    "difference and apply the strategy whatever the differences.",
)
@option(
    "-d",
    "--show-diff",
    is_flag=True,
    default=False,
    help="Show the unified diff of duplicates not within thresholds.",
)
@option(
    "-s",
    "--strategy",
    type=Choice(sorted(STRATEGY_METHODS), case_sensitive=False),
    help="Selection strategy to apply within a subset of duplicates. If not set, "
    "duplicates will be grouped and counted but all be skipped, selection will be "
    "empty, and no action will be performed. Description of each strategy is "
    "available further down that help screen.",
)
@option(
    "-t",
    "--time-source",
    default=DATE_HEADER,
    type=Choice(sorted(TIME_SOURCES), case_sensitive=False),
    help="Source of a mail's time reference used in time-sensitive strategies.",
)
@option(
    "-r",
    "--regexp",
    callback=validate_regexp,
    metavar="REGEXP",
    help="Regular expression on a mail's file path. Applies to real, individual "
    "mail location for folder-based boxed "
    f"({', '.join(sorted(BOX_STRUCTURES['folder']))}). But for file-based boxes "
    f"({', '.join(sorted(BOX_STRUCTURES['file']))}), applies to the whole box's path, "
    "as all mails are packed into one single file. Required in "
    f"{DISCARD_MATCHING_PATH}, {DISCARD_NON_MATCHING_PATH}, {SELECT_MATCHING_PATH} and "
    f"{SELECT_NON_MATCHING_PATH} strategies.",
)
@option(
    "-a",
    "--action",
    default=COPY_SELECTED,
    type=Choice(sorted(ACTIONS), case_sensitive=False),
    help=f"Action performed on the selected mails. Defaults to {COPY_SELECTED} as it "
    "is the safest: it only reads the mail sources and create a brand new mail box "
    "with the selection results.",
)
@option(
    "-E",
    "--export",
    metavar="MAIL_BOX_PATH",
    type=ClickPath(resolve_path=True),
    help="Location of the destination mail box to where to copy or move deduplicated "
    f"mails. Required in {COPY_SELECTED}, {COPY_DISCARDED}, "
    f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
)
@option(
    "-e",
    "--export-format",
    default="mbox",
    type=Choice(sorted(BOX_TYPES), case_sensitive=False),
    help="Format of the mail box to which deduplication mails will be exported to. "
    f"Only affects {COPY_SELECTED}, {COPY_DISCARDED}, "
    f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
)
@option(
    "--export-append",
    is_flag=True,
    default=False,
    help="If destination mail box already exists, add mails into it "
    "instead of interrupting (default behavior). "
    f"Affect {COPY_SELECTED}, {COPY_DISCARDED}, "
    f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
)
@argument(
    "mail_sources",
    nargs=-1,
    metavar="MAIL_SOURCE_1 MAIL_SOURCE_2 ...",
    type=ClickPath(exists=True, resolve_path=True),
)
@pass_context
def mdedup(
    ctx,
    dry_run,
    input_format,
    force_unlock,
    hash_only,
    hash_header,
    hash_body,
    size_threshold,
    content_threshold,
    show_diff,
    strategy,
    time_source,
    regexp,
    action,
    export,
    export_format,
    export_append,
    mail_sources,
):
    """Deduplicate mails from a set of mail boxes.

    \b
    Process:
    ● Phase #1: run a first pass to compute from their headers (and optionaly their body)
                the canonical hash of each encountered mail.
    ● Phase #2: a second pass to apply the selection strategy on each subset of
                duplicate mails sharing the same hash.
    ● Phase #3: perform an action on all selected mails.

    Action on the selected mails in phase #3 is only performed if no major differences
    between mails are uncovered during a fine-grained check differences in the second
    phase. Limits can be set via the --size-threshold and --content-threshold
    options, and are used as safety checks to prevent slightly different mails
    to be seen as similar through the lens of normalization.
    """
    # Print help screen and exit if no mail source provided.
    if not mail_sources:
        # Same as click_extra.colorize.HelpOption.print_help.
        echo(ctx.get_help(), color=ctx.color)
        ctx.exit()

    # Validate exclusive options requirement depending on strategy or action.
    validation_requirements = {
        strategy: (
            (
                regexp,
                "-r/--regexp",
                {
                    DISCARD_MATCHING_PATH,
                    DISCARD_NON_MATCHING_PATH,
                    SELECT_MATCHING_PATH,
                    SELECT_NON_MATCHING_PATH,
                },
            ),
        ),
        action: (
            (
                export,
                "-E/--export",
                {
                    COPY_SELECTED,
                    COPY_DISCARDED,
                    MOVE_SELECTED,
                    MOVE_DISCARDED,
                },
            ),
        ),
    }

    for conf_value, requirements in validation_requirements.items():
        for param_value, param_name, required_values in requirements:
            if conf_value in required_values:
                if not param_value:
                    raise BadParameter(
                        f"{conf_value} requires the {param_name} parameter."
                    )
            elif param_value:
                raise BadParameter(
                    f"{param_name} parameter not allowed in {conf_value}."
                )

    conf = Config(
        dry_run=dry_run,
        input_format=input_format,
        force_unlock=force_unlock,
        hash_only=hash_only,
        hash_headers=hash_header,
        hash_body=hash_body,
        size_threshold=size_threshold,
        content_threshold=content_threshold,
        show_diff=show_diff,
        strategy=strategy,
        time_source=time_source,
        regexp=regexp,
        action=action,
        export=export,
        export_format=export_format,
        export_append=export_append,
    )

    dedup = Deduplicate(conf)

    echo(theme.heading("\n● Phase #0 - Load mails"))
    with progressbar(
        mail_sources,
        length=len(mail_sources),
        label="Mail sources",
        show_pos=True,
    ) as progress:
        for source in progress:
            dedup.add_source(source)

    echo(theme.heading("\n● Phase #1 - Compute hashes and group duplicates"))
    dedup.hash_all()
    if hash_only:
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                echo(mail.pretty_headers)
                echo(f"Hash: {mail.hash_key}")
        ctx.exit()

    echo(theme.heading("\n● Phase #2 - Select mails in each group"))
    dedup.build_sets()

    echo(theme.heading("\n● Phase #3 - Perform action on selected mails"))
    perform_action(dedup)
    dedup.close_all()

    echo(theme.heading("\n● Phase #4 - Report and statistics"))
    # Print deduplication statistics, then performs a self-check on them.
    echo(dedup.report())
    dedup.check_stats()
