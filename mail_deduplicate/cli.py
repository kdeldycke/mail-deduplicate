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

from __future__ import annotations

import re
from typing import Callable, Pattern

from click_extra import (
    BadParameter,
    Choice,
    Context,
    ExtraCommand,
    HelpExtraFormatter,
    Parameter,
    argument,
    echo,
    extra_command,
    option,
    option_group,
    pass_context,
    path,
    progressbar,
)
from click_extra.colorize import default_theme as theme

from mail_deduplicate import (
    DATE_HEADER,
    DEFAULT_CONTENT_THRESHOLD,
    DEFAULT_SIZE_THRESHOLD,
    HASH_HEADERS,
    TIME_SOURCES,
    Config,
)
from mail_deduplicate.action import (
    ACTIONS,
    COPY_DISCARDED,
    COPY_SELECTED,
    MOVE_DISCARDED,
    MOVE_SELECTED,
    perform_action,
)
from mail_deduplicate.deduplicate import (
    BODY_HASHER_NORMALIZED,
    BODY_HASHER_RAW,
    BODY_HASHER_SKIP,
    BODY_HASHERS,
    Deduplicate,
)
from mail_deduplicate.mail_box import BOX_STRUCTURES, BOX_TYPES
from mail_deduplicate.strategy import (
    DISCARD_MATCHING_PATH,
    DISCARD_NON_MATCHING_PATH,
    SELECT_MATCHING_PATH,
    SELECT_NON_MATCHING_PATH,
    STRATEGY_METHODS,
)


def validate_regexp(ctx: Context, param: Parameter, value: str) -> str | Pattern[str]:
    """Validate and compile regular expression provided as parameters to the CLI."""
    if not value:
        return ""

    try:
        return re.compile(value)
    except ValueError:
        msg = "invalid regular expression."
        raise BadParameter(msg)


class MdedupCommand(ExtraCommand):
    def format_help(
        self,
        ctx: Context,
        formatter: HelpExtraFormatter,  # type: ignore[override]
    ) -> None:
        """Extend the help screen with the description of all available strategies."""
        # Populate the formatter with the default help screen content.
        super().format_help(ctx, formatter)

        # Produce the strategy reference table, with grouped aliases.
        method_to_ids: dict[Callable, list[str]] = {}
        for strategy_id, method in sorted(STRATEGY_METHODS.items(), reverse=True):
            method_to_ids.setdefault(method, []).append(strategy_id)

        strategy_table: list[tuple[str, str]] = []
        for method, strategy_ids in method_to_ids.items():
            row_title = f"[{'|'.join(strategy_ids)}]"
            row_desc = ""
            if method.__doc__:
                row_desc = " ".join(method.__doc__.split())
            strategy_table.append((row_title, row_desc))

        with formatter.section("Available strategies"):
            formatter.write_dl(sorted(strategy_table))


@extra_command(
    cls=MdedupCommand,
    short_help="Deduplicate mail boxes.",
    # Force linear layout for definition lists. See:
    # https://cloup.readthedocs.io/en/stable/pages/formatting.html#the-linear-layout-for-definition-lists
    formatter_settings={"col2_min_width": 9999999999},
    context_settings={
        # Removes the -h short option as we reserve it for --hash-header.
        "help_option_names": ("--help",),
        # XXX Default verbosity has been changed in Click Extra v4.0.0 from INFO
        # to WARNING.
        "default_map": {"verbosity": "INFO"},
    },
)
@option_group(
    "Mail sources (step #1)",
    option(
        "-i",
        "--input-format",
        type=Choice(sorted(BOX_TYPES), case_sensitive=False),
        help="Force all provided mail sources to be parsed in the specified format. "
        "If not set, auto-detect the format of sources independently. Auto-detection "
        "only supports maildir and mbox format. Use this option to open up other box "
        "format, or bypass unreliable detection.",
    ),
    option(
        "-u",
        "--force-unlock",
        is_flag=True,
        default=False,
        help="Remove the lock on mail source opening if one is found.",
    ),
)
@option_group(
    "Hashing (step #2)",
    option(
        "-h",
        "--hash-header",
        multiple=True,
        type=str,
        metavar="Header-ID",
        default=HASH_HEADERS,
        help="Headers to use to compute each mail's hash. Must be repeated multiple "
        "times to set an ordered list of headers. Header IDs are case-insensitive. "
        "Repeating entries are ignored.",
    ),
    option(
        "-b",
        "--hash-body",
        default=BODY_HASHER_SKIP,
        type=Choice(sorted(BODY_HASHERS), case_sensitive=False),
        help=f"Method used to hash the body of mails. Defaults to {BODY_HASHER_SKIP}, "
        "which doesn't hash the body at all: it is the fastest method and header-based "
        f"hash should be sufficient to determine duplicate set. {BODY_HASHER_RAW} use "
        f"the body as it is (slow). {BODY_HASHER_NORMALIZED} pre-process the body "
        "before hashing, by removing all line breaks and spaces (slowest).",
    ),
    option(
        "-H",
        "--hash-only",
        is_flag=True,
        default=False,
        help="Compute and display the internal hashes used to identify duplicates. Do "
        "not performs any selection or action.",
    ),
)
@option_group(
    "Deduplication (step #3)",
    (
        "Process each set of mails sharing the same hash and apply the "
        "selection --strategy. Fine-grained checks on size and content are performed "
        "beforehand. If differences are above safety "
        "levels, the whole duplicate set will be skipped. Limits can be set via "
        "the --size-threshold and --content-threshold options."
    ),
    option(
        "-s",
        "--strategy",
        type=Choice(sorted(STRATEGY_METHODS), case_sensitive=False),
        help="Selection strategy to apply within a subset of duplicates. If not set, "
        "duplicates will be grouped and counted but all be skipped, selection will be "
        "empty, and no action will be performed. Description of each strategy is "
        "available further down that help screen.",
    ),
    option(
        "-t",
        "--time-source",
        default=DATE_HEADER,
        type=Choice(sorted(TIME_SOURCES), case_sensitive=False),
        help="Source of a mail's time reference used in time-sensitive strategies.",
    ),
    option(
        "-r",
        "--regexp",
        callback=validate_regexp,
        metavar="REGEXP",
        help="Regular expression on a mail's file path. Applies to real, individual "
        "mail location for folder-based boxed "
        f"({', '.join(sorted(BOX_STRUCTURES['folder']))}). But for file-based boxes "
        f"({', '.join(sorted(BOX_STRUCTURES['file']))}), applies to the whole box's "
        "path, as all mails are packed into one single file. Required in "
        f"{DISCARD_MATCHING_PATH}, {DISCARD_NON_MATCHING_PATH}, "
        f"{SELECT_MATCHING_PATH} and {SELECT_NON_MATCHING_PATH} strategies.",
    ),
    option(
        "-S",
        "--size-threshold",
        type=int,
        metavar="BYTES",
        default=DEFAULT_SIZE_THRESHOLD,
        help="Maximum difference allowed in size between mails sharing the same hash. "
        "The whole subset of duplicates will be skipped if at least one pair of mail "
        "exceeds the threshold. Set to 0 to enforce strictness and apply selection "
        "strategy on the subset only if all mails are exactly the same. Set to -1 to "
        "allow any difference and apply the strategy whatever the differences.",
    ),
    option(
        "-C",
        "--content-threshold",
        type=int,
        metavar="BYTES",
        default=DEFAULT_CONTENT_THRESHOLD,
        help="Maximum difference allowed in content between mails sharing the same "
        "hash. The whole subset of duplicates will be skipped if at least one pair of "
        "mail exceeds the threshold. Set to 0 to enforce strictness and apply "
        "selection strategy on the subset only if all mails are exactly the same. Set "
        "to -1 to allow any difference and apply the strategy whatever the "
        "differences.",
    ),
    option(
        "-d",
        "--show-diff",
        is_flag=True,
        default=False,
        help="Show the unified diff of duplicates not within thresholds.",
    ),
)
@option_group(
    "Action (step #4)",
    option(
        "-a",
        "--action",
        default=COPY_SELECTED,
        type=Choice(sorted(ACTIONS), case_sensitive=False),
        help=f"Action performed on the selected mails. Defaults to {COPY_SELECTED} as "
        "it is the safest: it only reads the mail sources and create a brand new mail "
        "box with the selection results.",
    ),
    option(
        "-E",
        "--export",
        metavar="MAIL_BOX_PATH",
        type=path(resolve_path=True),
        help="Location of the destination mail box to where to copy or move "
        f"deduplicated mails. Required in {COPY_SELECTED}, {COPY_DISCARDED}, "
        f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
    ),
    option(
        "-e",
        "--export-format",
        default="mbox",
        type=Choice(sorted(BOX_TYPES), case_sensitive=False),
        help="Format of the mail box to which deduplication mails will be exported to. "
        f"Only affects {COPY_SELECTED}, {COPY_DISCARDED}, "
        f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
    ),
    option(
        "--export-append",
        is_flag=True,
        default=False,
        help="If destination mail box already exists, add mails into it "
        "instead of interrupting (default behavior). "
        f"Affect {COPY_SELECTED}, {COPY_DISCARDED}, "
        f"{MOVE_SELECTED} and {MOVE_DISCARDED} actions.",
    ),
    option(
        "-n",
        "--dry-run",
        is_flag=True,
        default=False,
        help="Do not perform any action but act as if it was, and report which action "
        "would have been performed otherwise.",
    ),
)
@argument(
    "mail_sources",
    nargs=-1,
    metavar="MAIL_SOURCE_1 MAIL_SOURCE_2 ...",
    type=path(exists=True, resolve_path=True),
    help="Mail sources to deduplicate. Can be a single mail box or a list of mails.",
)
@pass_context
def mdedup(
    ctx,
    input_format,
    force_unlock,
    hash_header,
    hash_body,
    hash_only,
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
    dry_run,
    mail_sources,
):
    """Deduplicate mails from multiple sources.

    \b
    Process:
    ● Step #1: load mails from their sources.
    ● Step #2: compute the canonical hash of each mail based on their headers (and
               optionally their body), and regroup mails sharing the same hash.
    ● Step #3: apply a selection strategy on each subset of duplicate mails.
    ● Step #4: perform an action on all selected mails.
    ● Step #5: report statistics.
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
                    msg = f"{conf_value} requires the {param_name} parameter."
                    raise BadParameter(msg)
            elif param_value:
                msg = f"{param_name} parameter not allowed in {conf_value}."
                raise BadParameter(msg)

    conf = Config(
        dry_run=dry_run,
        input_format=input_format,
        force_unlock=force_unlock,
        hash_headers=hash_header,
        hash_body=hash_body,
        hash_only=hash_only,
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

    echo(theme.heading("\n● Step #1 - Load mails"))
    with progressbar(
        mail_sources,
        length=len(mail_sources),
        label="Mail sources",
        show_pos=True,
    ) as progress:
        for source in progress:
            dedup.add_source(source)

    echo(theme.heading("\n● Step #2 - Compute hashes and group duplicates"))
    dedup.hash_all()
    if hash_only:
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                echo(mail.pretty_headers)
                echo(f"Hash: {mail.hash_key()}")
        ctx.exit()

    echo(theme.heading("\n● Step #3 - Select mails in each group"))
    dedup.build_sets()

    echo(theme.heading("\n● Step #4 - Perform action on selected mails"))
    perform_action(dedup)
    dedup.close_all()

    echo(theme.heading("\n● Step #5 - Report and statistics"))
    # Print deduplication statistics, then performs a self-check on them.
    echo(dedup.report())
    dedup.check_stats()
