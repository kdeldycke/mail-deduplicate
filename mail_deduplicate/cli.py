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

import logging
import re
from typing import TypedDict

from click_extra import (
    BadParameter,
    Command,
    EnumChoice,
    IntRange,
    ParameterSource,
    argument,
    command,
    constraint,
    echo,
    get_current_theme,
    jobs_option,
    option,
    option_group,
    pass_context,
    path,
    progressbar,
)
from cloup.constraints import If, accept_none, require_all
from cloup.constraints.conditions import Predicate

from .action import Action
from .cache import default_cache_path
from .deduplicate import BodyHasher, Deduplicate
from .mail import TimeSource
from .mail_box import FILE_FORMATS, FOLDER_FORMATS, BoxFormat
from .strategy import Strategy

TYPE_CHECKING = False
if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    import click
    from click_extra import Context, HelpFormatter, Parameter


DEFAULT_HASH_HEADERS: tuple[str, ...] = (
    "Date",
    "From",
    "To",
    # "CC",
    # "BCC",
    # "Reply-To",
    "Subject",
    "MIME-Version",
    "Content-Type",
    "Content-Disposition",
    "User-Agent",
    "X-Priority",
    "Message-ID",
)
"""Default ordered list of headers to use to compute the unique hash of a mail.

By default we choose to exclude:

`CC`
  Since `mailman` apparently [sometimes trims list members](https://mail.python.org/pipermail/mailman-developers/2002-September/013233.html)
  from the `CC` header to avoid sending duplicates. Which means that copies of mail
  reflected back from the list server will have a different `CC` to the copy saved by
  the MUA at send-time.

`BCC`
  Because copies of the mail saved by the MUA at send-time will have `BCC`, but copies
  reflected back from the list server won't.

`Reply-To`
  Since a mail could be `CC`'d to two lists with different `Reply-To` munging
  options set.
"""


DEFAULT_MINIMAL_HEADERS = 4
"""Cap on the number of headers that must be present in a mail to compute a solid hash.

The per-mail floor is `min(DEFAULT_MINIMAL_HEADERS, len(hash_headers))`: it rejects
near-empty or corrupted mails whose hash would rest on too few headers, while relaxing
automatically when the hash is narrowed to fewer headers than this cap via
`--hash-header`.
"""


class Config(TypedDict):
    """Holds global configuration."""

    input_format: BoxFormat | None
    force_unlock: bool
    hash_headers: tuple[str, ...]
    minimal_headers: int
    hash_body: BodyHasher
    hash_only: bool
    cache: bool
    cache_path: Path | None
    size_threshold: int
    content_threshold: int
    show_diff: bool
    strategies: tuple[Strategy, ...]
    time_source: TimeSource
    regexp: re.Pattern | None
    action: Action
    export: Path | None
    export_format: BoxFormat
    export_append: bool
    hardlink_differing: bool
    dry_run: bool


def normalize_headers(
    ctx: Context, param: Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate headers provided as parameters to the CLI.

    Headers are case-insensitive in Python implementation, so we normalize them to
    lower-case.

    We then deduplicate them, while preserving order.

    Mail headers are expected to be composed of ASCII characters between 33 and 126
    (both inclusive) according to RFC-5322.
    """
    normalized_headers = tuple(dict.fromkeys(h.lower() for h in value))
    for hid in normalized_headers:
        ascii_indexes = set(map(ord, hid))
        if min(ascii_indexes) < 33 or max(ascii_indexes) > 126:
            raise BadParameter(f"invalid header ID: {hid!r}.")
    if len(normalized_headers) == 0:
        raise BadParameter("At least one header ID must be provided.")
    return normalized_headers


def unique_strategies(
    ctx: Context, param: Parameter, value: tuple[Strategy, ...]
) -> tuple[Strategy, ...]:
    """Deduplicate strategies provided as parameters to the CLI, preserving order.

    Strategies are deduplicated by the selection function they point to, so repeating
    a strategy already listed under one of its aliases is ignored too.
    """
    deduplicated: dict[Callable, Strategy] = {}
    for strategy in value:
        deduplicated.setdefault(strategy.strategy_function, strategy)
    return tuple(deduplicated.values())


def compile_regexp(
    ctx: Context, param: Parameter, value: str
) -> re.Pattern[str] | None:
    """Validate and compile regular expression provided as parameters to the CLI."""
    if value:
        try:
            return re.compile(value)
        except re.error:
            raise BadParameter(f"invalid regular expression: {value!r}.")
    return None


PATH_STRATEGIES = frozenset((
    Strategy.DISCARD_MATCHING_PATH,
    Strategy.DISCARD_NON_MATCHING_PATH,
    Strategy.SELECT_MATCHING_PATH,
    Strategy.SELECT_NON_MATCHING_PATH,
))
"""Strategies relying on the `-r`/`--regexp` parameter."""


EXPORT_ACTIONS = frozenset((
    Action.COPY_SELECTED,
    Action.COPY_DISCARDED,
    Action.MOVE_SELECTED,
    Action.MOVE_DISCARDED,
))
"""Actions relying on the `-E`/`--export` parameter."""


class AnyValueIn(Predicate):
    """Condition that is true when any of a parameter's values is in a target set.

    The parameter's resolved value is inspected, so defaults count, not only
    user-provided values. Single values and `multiple=True` tuples are normalized
    to a common shape. Set `negate` to invert the membership test: true when none
    of the values is in the target set.

    Whatever `negate` says, the condition silently evaluates to false when no mail
    source is provided: the CLI then only prints its help screen and exits, so no
    parameter combination deserves a validation error.

    The same applies in `-H`/`--hash-only` mode: selection and action steps
    never run there, so options they require (like `--export` for the default
    copy-selected action) must not be demanded. Options from those steps are
    separately reported as ignored by the hash-only code path.
    """

    def __init__(
        self, param_name: str, targets: Iterable, label: str, negate: bool = False
    ) -> None:
        self.param_name = param_name
        self.targets = frozenset(targets)
        self.label = label
        self.negate = negate

    def description(self, ctx: click.Context) -> str:
        quantifier = "none of" if self.negate else "one of"
        target_ids = ", ".join(sorted(map(str, self.targets)))
        return f"{self.label} is {quantifier} {target_ids}"

    def __call__(self, ctx: click.Context) -> bool:
        if not ctx.params.get("mail_sources") or ctx.params.get("hash_only"):
            return False
        value = ctx.params[self.param_name]
        if value is None:
            value = ()
        elif not isinstance(value, tuple):
            value = (value,)
        return self.targets.isdisjoint(value) == self.negate


class MdedupCommand(Command):
    def format_help(
        self,
        ctx: Context,  # type: ignore[override]
        formatter: HelpFormatter,  # type: ignore[override]
    ) -> None:
        """Extend the help screen with the description of all available strategies."""
        # Populate the formatter with the default help screen content.
        super().format_help(ctx, formatter)

        # Produce the strategy reference table, with grouped aliases.
        method_to_ids: dict[Callable, list[str]] = {}
        for strategy in Strategy:
            method = strategy.strategy_function
            if method not in method_to_ids:
                method_to_ids[method] = []
            method_to_ids[method].append(str(strategy))

        strategy_table: list[tuple[str, str]] = []
        for method, strategy_ids in method_to_ids.items():
            row_title = f"[{'|'.join(strategy_ids)}]"
            row_desc = ""
            if method.__doc__:
                row_desc = " ".join(method.__doc__.split())
            strategy_table.append((row_title, row_desc))

        with formatter.section("Available strategies"):
            formatter.write_dl(sorted(strategy_table))


@command(
    cls=MdedupCommand,
    short_help="Deduplicate mail boxes.",
    # Refuse configuration files carrying keys that match no CLI option: a
    # silently ignored typo can turn a destructive run into the wrong one.
    config_strict=True,
    # Mail sources must be provided on the command line, never from a
    # configuration file: a stale entry would silently point a bare `mdedup`
    # call at real mail boxes.
    excluded_params=["mdedup.mail_sources"],
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
        type=EnumChoice(BoxFormat),
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
        "hash_headers",
        multiple=True,
        type=str,
        callback=normalize_headers,
        metavar="Header-ID",
        default=DEFAULT_HASH_HEADERS,
        help="Headers to use to compute each mail's hash. Must be repeated multiple "
        "times to set an ordered list of headers. Header IDs are case-insensitive. "
        "Repeating entries are ignored.",
    ),
    option(
        "-b",
        "--hash-body",
        default=BodyHasher.SKIP,
        type=EnumChoice(BodyHasher),
        help=f"Method used to hash the body of mails. Defaults to {BodyHasher.SKIP}, "
        "which doesn't hash the body at all: it is the fastest method and header-based "
        f"hash should be sufficient to determine duplicate set. {BodyHasher.RAW} use "
        f"the body as it is (slow). {BodyHasher.NORMALIZED} pre-process the body "
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
    option(
        "--cache/--no-cache",
        default=False,
        help="Reuse the hashes computed by previous runs, so unchanged mails are not "
        "read nor parsed again. An entry is only trusted while the size and "
        "modification time of the file backing its mail are unchanged, and the whole "
        "cache is discarded as soon as any option feeding the hashes changes. Mails "
        "of a file-based box (mbox, babyl, mmdf) all share the box's file, so editing "
        "it invalidates every one of them at once. Off by default.",
    ),
    option(
        "--cache-path",
        metavar="CACHE_DB_PATH",
        type=path(dir_okay=False, resolve_path=True),
        default=None,
        help="Location of the hash cache database. Implies --cache. Defaults to "
        f"{default_cache_path()}",
    ),
)
@option_group(
    "Deduplication (step #3)",
    (
        "Process each set of mails sharing the same hash and apply the "
        "selection --strategy. Fine-grained checks on size and content are performed "
        "beforehand. Mails differing above safety levels are set aside so the rest "
        "can still be deduplicated, and the set is skipped if fewer than 2 remain. "
        "Limits can be set via "
        "the --size-threshold and --content-threshold options."
    ),
    option(
        "-s",
        "--strategy",
        "strategies",
        multiple=True,
        type=EnumChoice(Strategy),
        callback=unique_strategies,
        help="Selection strategy to apply within a subset of duplicates. Can be "
        "repeated multiple times to set an ordered list of fallback strategies: each "
        "duplicate set is handed over to the next strategy each time a strategy "
        "fails to discriminate its mails, by selecting all of them, none of them, or "
        "by missing the timestamps to compare them. Repeating entries are ignored, "
        "including aliases of strategies already listed. If not set, duplicates will "
        "be grouped and counted but all be skipped, selection will be empty, and no "
        "action will be performed. Description of each strategy is available further "
        "down that help screen.",
    ),
    option(
        "-t",
        "--time-source",
        default=TimeSource.DATE_HEADER,
        type=EnumChoice(TimeSource),
        help="Source of a mail's time reference used in time-sensitive strategies.",
    ),
    option(
        "-r",
        "--regexp",
        callback=compile_regexp,
        metavar="REGEXP",
        help="Regular expression on a mail's file path. Applies to individual mail "
        "location for folder-based boxes ("
        f"{', '.join(map(str, FOLDER_FORMATS))}). But for file-based boxes ("
        f"{', '.join(map(str, FILE_FORMATS))}), applies to the whole box's "
        "path, as all mails are packed into one single file. Required in "
        f"{Strategy.DISCARD_MATCHING_PATH}, {Strategy.DISCARD_NON_MATCHING_PATH}, "
        f"{Strategy.SELECT_MATCHING_PATH} and {Strategy.SELECT_NON_MATCHING_PATH} "
        "strategies.",
    ),
    option(
        "-S",
        "--size-threshold",
        type=IntRange(min=-1),
        metavar="BYTES",
        default=512,
        help="Maximum difference allowed in size between mails sharing the same hash. "
        "Mails in an offending pair are set aside until the rest all pass. The "
        "subset is skipped if fewer than 2 remain. "
        "Set to 0 to enforce strictness and apply selection "
        "strategy on the subset only if all mails are exactly the same. Set to -1 to "
        "allow any difference and apply the strategy whatever the differences.",
    ),
    option(
        "-C",
        "--content-threshold",
        type=IntRange(min=-1),
        metavar="BYTES",
        default=768,
        help="Maximum difference allowed in content between mails sharing the same "
        "hash. Mails in an offending pair are set aside until the rest all pass. The "
        "subset is skipped if fewer than 2 remain. "
        "Set to 0 to enforce strictness and apply "
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
        default=Action.COPY_SELECTED,
        type=EnumChoice(Action),
        help=f"Action performed on the selected mails. Defaults to "
        f"{Action.COPY_SELECTED} as it is the safest: it only reads the mail sources "
        "and create a brand new mail box with the selection results.",
    ),
    option(
        "-E",
        "--export",
        metavar="MAIL_BOX_PATH",
        type=path(resolve_path=True),
        help="Location of the destination mail box to where to copy or move "
        f"deduplicated mails. Required in {Action.COPY_SELECTED}, "
        f"{Action.COPY_DISCARDED}, {Action.MOVE_SELECTED} and {Action.MOVE_DISCARDED} "
        "actions.",
    ),
    option(
        "-e",
        "--export-format",
        default=BoxFormat.MBOX,
        type=EnumChoice(BoxFormat),
        help="Format of the mail box to which deduplication mails will be exported to. "
        f"Only affects {Action.COPY_SELECTED}, {Action.COPY_DISCARDED}, "
        f"{Action.MOVE_SELECTED} and {Action.MOVE_DISCARDED} actions.",
    ),
    option(
        "--export-append",
        is_flag=True,
        default=False,
        help="If destination mail box already exists, add mails into it "
        "instead of interrupting (default behavior). "
        f"Affect {Action.COPY_SELECTED}, {Action.COPY_DISCARDED}, "
        f"{Action.MOVE_SELECTED} and {Action.MOVE_DISCARDED} actions.",
    ),
    option(
        "--hardlink-differing",
        is_flag=True,
        default=False,
        help="Hardlink discarded mails whose content differs byte for byte from the "
        "copy they are linked to, instead of leaving them alone. Their own content is "
        "then swapped for that copy's, so whatever was unique to them, like the "
        "headers a mail collects on its way to one account, is lost. "
        f"Only affects the {Action.HARDLINK_DISCARDED} action.",
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
# Enforce the parameters that must accompany, or are forbidden by, specific
# --strategy and --action values. Each rule is split into a requiring and a
# forbidding constraint so each side reports the condition that actually
# triggered it, without dragging the other into the error message.
@constraint(
    If(AnyValueIn("strategies", PATH_STRATEGIES, "-s/--strategy"), then=require_all),
    ["regexp"],
)
@constraint(
    If(
        AnyValueIn("strategies", PATH_STRATEGIES, "-s/--strategy", negate=True),
        then=accept_none,
    ),
    ["regexp"],
)
@constraint(
    If(AnyValueIn("action", EXPORT_ACTIONS, "-a/--action"), then=require_all),
    ["export"],
)
@constraint(
    If(
        AnyValueIn("action", EXPORT_ACTIONS, "-a/--action", negate=True),
        then=accept_none,
    ),
    ["export"],
)
@argument(
    "mail_sources",
    nargs=-1,
    metavar="MAIL_SOURCE_1 MAIL_SOURCE_2 ...",
    type=path(exists=True, resolve_path=True),
    help="Mail sources to deduplicate. Can be a single mail box or a list of mails.",
)
@jobs_option(
    default=1,
    help=(
        "Number of parallel jobs used to hash mails (step #2). Accepts an integer, "
        "'auto' (one fewer than the host's logical CPUs) or 'max'. Defaults to 1 "
        "(sequential); higher values speed up --hash-body raw/normalized on large "
        "boxes."
    ),
)
@pass_context
def mdedup(
    ctx,
    input_format,
    force_unlock,
    hash_headers,
    hash_body,
    hash_only,
    cache,
    cache_path,
    size_threshold,
    content_threshold,
    show_diff,
    strategies,
    time_source,
    regexp,
    action,
    export,
    export_format,
    export_append,
    hardlink_differing,
    dry_run,
    mail_sources,
):
    """Deduplicate mails from multiple sources.

    \b
    Process:
    - Step #1: load mails from their sources.
    - Step #2: compute the canonical hash of each mail based on their headers (and
               optionally their body), and regroup mails sharing the same hash.
    - Step #3: apply a selection strategy on each subset of duplicate mails.
    - Step #4: perform an action on all selected mails.
    - Step #5: report statistics.
    """
    # Print help screen and exit if no mail source provided.
    if not mail_sources:
        # Same as Click Extra's HelpOption.print_help.
        echo(ctx.get_help(), color=ctx.color)
        ctx.exit()

    if export and export.exists() and not export_append:
        raise FileExistsError(
            f"Cannot export to existing file {export!r} unless --export-append is set."
        )

    conf = Config(
        input_format=input_format,
        force_unlock=force_unlock,
        hash_headers=hash_headers,
        minimal_headers=min(DEFAULT_MINIMAL_HEADERS, len(hash_headers)),
        hash_body=hash_body,
        hash_only=hash_only,
        # An explicit database location is a request to use it.
        cache=cache or cache_path is not None,
        cache_path=cache_path,
        size_threshold=size_threshold,
        content_threshold=content_threshold,
        show_diff=show_diff,
        strategies=strategies,
        time_source=time_source,
        regexp=regexp,
        action=action,
        export=export,
        export_format=export_format,
        export_append=export_append,
        hardlink_differing=hardlink_differing,
        dry_run=dry_run,
    )

    dedup = Deduplicate(conf)

    theme = get_current_theme()
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
        # List options attached to the sections specifics to later steps, that were
        # provided by the user.
        ignored_user_options: list[str] = []
        for group in ctx.command.option_groups:
            step_number = re.search(r"step #(\d+)", group.title)
            if not step_number:
                raise RuntimeError("Option group not associated to a step number.")
            # Only collect options from steps after #2.
            if int(step_number.group(1)) > 2:
                ignored_user_options.extend(
                    "/".join(opt.opts + opt.secondary_opts)
                    for opt in group.options
                    if ctx.get_parameter_source(opt.name) != ParameterSource.DEFAULT
                )
        if ignored_user_options:
            logging.warning(
                "Options provided by user, but ignored in -H/--hash-only mode: "
                + ", ".join(ignored_user_options)
            )

        # Print all computed hashes. Rendering the canonical headers needs the full
        # message back, so borrow it one mail at a time to keep memory flat.
        for all_mails in dedup.mails.values():
            for mail in all_mails:
                with mail.hydrated():
                    echo(mail.pretty_canonical_headers())
                    echo(f"Hash: {mail.hash_key()}")

        # Exit right away, releasing the boxes and the cache on the way out.
        dedup.close_all()
        ctx.exit()

    echo(theme.heading("\n● Step #3 - Select mails in each group"))
    dedup.build_sets()

    echo(theme.heading("\n● Step #4 - Perform action on selected mails"))
    action.perform_action(dedup)
    dedup.close_all()

    echo(theme.heading("\n● Step #5 - Report and statistics"))
    # Print deduplication statistics, then performs a self-check on them.
    echo(dedup.report())
    dedup.check_stats()
