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
"""The `mdedup` command: its options, their validation and the run `Config`."""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any, TypedDict

from click_extra import (
    BadParameter,
    ClickException,
    Command,
    EnumChoice,
    IntRange,
    ParameterSource,
    UsageError,
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
)
from cloup.constraints import If, accept_none, require_all
from cloup.constraints.conditions import Predicate

from .action import Action
from .bug_report import report_unexpected_errors
from .cache import default_cache_path
from .deduplicate import BodyHasher, Deduplicate, step_progressbar
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

The per-mail floor is `min(DEFAULT_MINIMAL_HEADERS, len(hash_headers))`. A near-empty
or corrupted mail whose hash would rest on too few headers gets no hash, and the run
keeps it like a mail without duplicates. The floor relaxes automatically when
`--hash-header` narrows the hash to fewer headers than this cap.
"""


class Preset(StrEnum):
    """Named sets of option values, each a starting point for a run.

    A preset is an alias of the options `PRESET_OPTIONS` lists for it.
    """

    CONSERVATIVE = "conservative"
    """Treats as copies only the mails whose bytes are identical."""

    DEFAULT = "default"
    """Keeps the built-in defaults."""

    AGGRESSIVE = "aggressive"
    """Trusts the `Message-ID` header alone to group copies."""


PRESET_OPTIONS: dict[Preset, tuple[tuple[str, str | bool], ...]] = {
    Preset.CONSERVATIVE: (
        ("--raw-headers", True),
        ("--hash-body", "raw"),
        ("--size-threshold", "-1"),
        ("--content-threshold", "-1"),
        ("--strategy", "select-one"),
    ),
    Preset.DEFAULT: (),
    Preset.AGGRESSIVE: (("--hash-header", "Message-ID"),),
}
"""The options each preset stands for, spelled as on the command line.

`apply_preset()` gives each of them its value, unless the user set that option. A
value that relies on other values of the same preset applies only while all of them
apply: see `DEPENDENT_OPTIONS`.

The conservative preset hashes the bytes of the whole mail, which only identical
copies share. The thresholds then have nothing left to catch, and turning them off
spares a second read of each mail. When the user replaces one of its two hashing
options, copies that differ can share a hash, so the thresholds stay on. Identical
copies are interchangeable, so the preset also keeps one of each.

The aggressive preset trusts `Message-ID` alone, so the copies whose other headers
a mailing list or a gateway rewrote still share a hash. The thresholds stay the
only check against two mails that reuse an ID. Its copies can differ, so which one
to keep stays the user's choice.
"""

LINKED_OPTIONS: tuple[frozenset[str], ...] = (
    frozenset(("hash_headers", "raw_headers")),
)
"""Options that make one choice between them, by their name.

`--raw-headers` hashes every header, so a `--hash-header` list has nothing left to
select. The user setting either option decides the headers, so a preset value for
the other one gives way too.
"""

DEPENDENT_OPTIONS: dict[str, frozenset[str]] = {
    "content_threshold": frozenset(("hash_body", "raw_headers")),
    "size_threshold": frozenset(("hash_body", "raw_headers")),
}
"""Options whose preset value relies on the preset values of others, by their name.

A preset value of such an option applies only while each option it relies on keeps
the value of the same preset: the preset gives that value, or the user gives the
same one. When one of them gives way, the option gives way too, and keeps its
default or the user's value. The rule ignores an option that the preset does not
set.

The thresholds can stay off only while the hash covers every byte of a mail, which
`--raw-headers` and `--hash-body raw` do together.
"""

QUIET_OVERRIDES = frozenset(("strategies",))
"""Options the user can set over a preset with no warning, by their name.

The strategy decides which copy stays, not what counts as a copy.
"""


def preset_word(flag: str, value: str | bool) -> str:
    """One option of a preset, as typed on the command line."""
    return flag if value is True else f"{flag} {value}"


def preset_words(preset: Preset) -> str:
    """The options a preset stands for, as typed on the command line."""
    return " ".join(preset_word(flag, value) for flag, value in PRESET_OPTIONS[preset])


class Config(TypedDict):
    """Holds global configuration."""

    input_format: BoxFormat | None
    force_unlock: bool
    raw_headers: bool
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

    Mail headers are expected to be composed of one or more ASCII characters between
    33 and 126 (both inclusive) according to RFC-5322.
    """
    normalized_headers = tuple(dict.fromkeys(h.lower() for h in value))
    for hid in normalized_headers:
        if not hid or not all(33 <= ord(char) <= 126 for char in hid):
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
        deduplicated.setdefault(strategy.function, strategy)
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


PATH_STRATEGIES = (
    Strategy.DISCARD_MATCHING_PATH,
    Strategy.DISCARD_NON_MATCHING_PATH,
    Strategy.SELECT_MATCHING_PATH,
    Strategy.SELECT_NON_MATCHING_PATH,
)
"""Strategies relying on the `-r`/`--regexp` parameter."""


EXPORT_ACTIONS = (
    Action.COPY_SELECTED,
    Action.COPY_DISCARDED,
    Action.MOVE_SELECTED,
    Action.MOVE_DISCARDED,
)
"""Actions relying on the `-E`/`--export` parameter."""


def echo_step(title: str) -> None:
    """Print the heading of a pipeline step, after a blank line.

    The blank line is printed on its own, outside the heading's style. Styled as
    part of the heading, its escapes open the style on the line above the text, so
    any tool reading the output line by line (a pager, `grep`, a capture cut with
    `--head`) finds a style open on a line that closes it nowhere.

    :param title: the step's name, after the bullet.
    """
    echo()
    echo(get_current_theme().heading(f"\N{BLACK CIRCLE} {title}"))


def human_join(items: Iterable) -> str:
    """Renders IDs as an English enumeration, for the help screen.

    Both tuples above are the single source of truth of which strategies and actions
    take an extra parameter, so the options mentioning them read the list from there
    instead of spelling it out again and drifting from it.
    """
    ids = [str(item) for item in items]
    return " and ".join((", ".join(ids[:-1]), ids[-1])) if len(ids) > 1 else ids[0]


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
            method_to_ids.setdefault(strategy.function, []).append(str(strategy))

        strategy_table: list[tuple[str, str]] = []
        for method, strategy_ids in method_to_ids.items():
            row_title = f"[{'|'.join(strategy_ids)}]"
            row_desc = ""
            if method.__doc__:
                row_desc = " ".join(method.__doc__.split())
            strategy_table.append((row_title, row_desc))

        with formatter.section("Available strategies"):
            formatter.write_dl(sorted(strategy_table))


def flag_names(param: Parameter) -> str:
    """Every spelling of an option, joined as the help screen lists them."""
    return "/".join(param.opts + param.secondary_opts)


def user_set(ctx: Context, name: str) -> bool:
    """Whether the user gave a parameter its value, from any source but its default.

    A value from a configuration file or the environment counts as set.
    """
    return ctx.get_parameter_source(name) not in (None, ParameterSource.DEFAULT)


def apply_preset(ctx: Context, preset: Preset) -> dict[str, Any]:
    """The values a preset gives the options the user left at their default.

    An option the user set keeps its value. The run warns about each one that
    overrides the preset with another value, unless `QUIET_OVERRIDES` lists it.
    The options of a `LINKED_OPTIONS` group give way together. A value that relies
    on other values of the preset, as `DEPENDENT_OPTIONS` lists, gives way with any
    of them, and the run names the options that then keep their defaults.

    :param ctx: the context of the run, holding the values of its parameters.
    :param preset: the preset to apply.
    :return: the value of each option the preset sets, by parameter name.
    """
    by_flag = {opt: param for param in ctx.command.params for opt in param.opts}
    by_name = {param.name: param for param in ctx.command.params}
    # The value and the spelling of each option of the preset, in its order.
    values: dict[str, Any] = {}
    words: dict[str, str] = {}
    # Options the preset gives a value to.
    given: set[str] = set()
    # Options that keep the value of the preset, from the preset or from the user.
    kept: set[str] = set()
    overriding: set[str] = set()
    for flag, raw in PRESET_OPTIONS[preset]:
        param = by_flag[flag]
        # Always set for an option.
        assert param.name is not None
        name = param.name
        values[name] = param.process_value(ctx, [raw] if param.multiple else raw)
        words[name] = preset_word(flag, raw)
        group = next(
            (group for group in LINKED_OPTIONS if name in group), frozenset((name,))
        )
        set_by_user = [other for other in sorted(group) if user_set(ctx, other)]
        if not set_by_user:
            given.add(name)
            kept.add(name)
        elif set_by_user == [name] and ctx.params[name] == values[name]:
            # The user asked for the value the preset gives.
            kept.add(name)
        elif name not in QUIET_OVERRIDES:
            overriding.update(flag_names(by_name[other]) for other in set_by_user)
    # A value that gives way breaks each value that relies on it, which can break
    # others in turn. Repeat until no value breaks, so the order of the preset does
    # not change the result.
    broken = True
    while broken:
        broken = False
        for name in sorted(kept):
            premises = DEPENDENT_OPTIONS.get(name, frozenset()) & values.keys()
            if not premises <= kept:
                kept.discard(name)
                broken = True
    applied = [word for name, word in words.items() if name in kept]
    if applied:
        # The options go on a log line of their own: they fill most of a terminal,
        # and a line folding one of them in two would read as another option.
        logging.info(f"Apply the options of the {preset} preset:")
        logging.info(" ".join(applied))
    if overriding:
        logging.warning(
            f"Options override the {preset} preset: {human_join(sorted(overriding))}."
        )
    defaults = sorted(flag_names(by_name[name]) for name in given - kept)
    if defaults:
        logging.info(
            f"Options keep their defaults, because their values in the {preset} "
            f"preset rely on overridden options: {human_join(defaults)}."
        )
    return {name: value for name, value in values.items() if name in given & kept}


def ignored_step_options(ctx) -> list[str]:
    """User-provided options from the steps `-H`/`--hash-only` never runs.

    Collects the options attached to the sections of steps after #2 whose value does
    not come from a default, so the run can report them as ignored.
    """
    ignored: list[str] = []
    for group in ctx.command.option_groups:
        step_number = re.search(r"step #(\d+)", group.title)
        # Click Extra files its own options (configuration, output, logging,
        # introspection) under groups of their own: they belong to no step, and
        # apply in every mode.
        if step_number and int(step_number.group(1)) > 2:
            ignored.extend(
                flag_names(opt) for opt in group.options if user_set(ctx, opt.name)
            )
    return ignored


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
    "Preset",
    option(
        "--preset",
        type=EnumChoice(Preset),
        default=Preset.DEFAULT,
        help="Start from the option values of a preset. "
        f"{Preset.CONSERVATIVE} treats as copies only the mails whose bytes are "
        f"identical, and stands for {preset_words(Preset.CONSERVATIVE)}. "
        f"{Preset.DEFAULT} keeps the built-in defaults. {Preset.AGGRESSIVE} trusts the "
        "Message-ID header alone to group copies, and stands for "
        f"{preset_words(Preset.AGGRESSIVE)}. An option set on the command line, in the "
        "environment or in a configuration file overrides the value the preset "
        f"gives it. {Preset.CONSERVATIVE} turns the thresholds off only with its own "
        "--raw-headers and --hash-body raw. When another value or a --hash-header "
        "list replaces either one, both thresholds keep their defaults.",
    ),
)
@option_group(
    "Mail sources (step #1)",
    option(
        "-i",
        "--input-format",
        type=EnumChoice(BoxFormat),
        help="Force all provided mail sources to be parsed in the specified format. "
        "If not set, auto-detect the format of sources independently. Auto-detection "
        "only supports maildir, mbox and eml formats. Use this option to open up "
        "other box formats, or bypass unreliable detection.",
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
        "--raw-headers/--no-raw-headers",
        default=False,
        help="Hash the header block of each mail as its box stores it, line endings "
        "aside: every header, in its order, with no normalization. Replaces the "
        "--hash-header list, so the two are refused together, and no minimal number "
        "of headers is required.",
    ),
    option(
        "-b",
        "--hash-body",
        default=BodyHasher.SKIP,
        type=EnumChoice(BodyHasher),
        help=f"Method used to hash the body of mails. Defaults to {BodyHasher.SKIP}, "
        "which doesn't hash the body at all: it is the fastest method and header-based "
        f"hash should be sufficient to determine duplicate set. {BodyHasher.RAW} "
        "hashes the body bytes as the box holds them, with no decoding. "
        f"{BodyHasher.DECODED} undoes the transfer encodings and decodes the text "
        "first, so copies that differ in their encoding alone hash the same (slow). "
        f"{BodyHasher.NORMALIZED} also strips all whitespace (slowest).",
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
        "including aliases of strategies already listed. If not set, every duplicate "
        "set is skipped: none of its mails is selected or discarded. The mails without "
        "duplicates stay selected, and a copy or a move still carries them. "
        "Description of each strategy is available further down that help screen.",
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
        f"{human_join(PATH_STRATEGIES)} strategies.",
    ),
    option(
        "-S",
        "--size-threshold",
        type=IntRange(min=-1),
        metavar="BYTES",
        default=512,
        help="Maximum difference allowed in size between mails sharing the same hash, "
        "in bytes of their decoded bodies. "
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
        "hash, in bytes of the diff of their decoded bodies. "
        "Mails in an offending pair are set aside until the rest all pass. The "
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
        "and create a brand new mail box with the selection results. Mails that have "
        f"no duplicate are part of the selection, but {Action.DELETE_SELECTED} leaves "
        "them in place, as deleting one removes the only copy of it there is.",
    ),
    option(
        "-E",
        "--export",
        metavar="MAIL_BOX_PATH",
        type=path(resolve_path=True),
        help="Location of the destination mail box to where to copy or move "
        f"deduplicated mails. Required in {human_join(EXPORT_ACTIONS)} actions.",
    ),
    option(
        "-e",
        "--export-format",
        default=BoxFormat.MBOX,
        type=EnumChoice(BoxFormat),
        help="Format of the mail box to which deduplication mails will be exported to. "
        f"Only affects {human_join(EXPORT_ACTIONS)} actions.",
    ),
    option(
        "--export-append",
        is_flag=True,
        default=False,
        help="If destination mail box already exists, add mails into it "
        "instead of interrupting (default behavior). "
        f"Affect {human_join(EXPORT_ACTIONS)} actions.",
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
        "Number of parallel jobs used to hash mails (step #2) and settle duplicate "
        "sets (step #3). Accepts an integer, 'auto' (the host's logical CPUs, "
        "minus one when there are three or more) or 'max'. Defaults to 1 "
        "(sequential). Only folder-based boxes fan out; higher values speed up "
        "--hash-body decoded/normalized and boxes holding many duplicate sets."
    ),
)
@pass_context
def mdedup(
    ctx,
    preset,
    input_format,
    force_unlock,
    hash_headers,
    raw_headers,
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

    # A header list selects nothing once every header is hashed. The user setting
    # both is a contradiction, where a preset setting either one gives way.
    if raw_headers and user_set(ctx, "raw_headers") and user_set(ctx, "hash_headers"):
        raise UsageError(
            "--raw-headers hashes every header, so -h/--hash-header has nothing to "
            "select: drop one of them."
        )

    if export and export.exists() and not export_append:
        raise ClickException(
            f"Cannot export to existing file {export} unless --export-append is set."
        )

    # Every option of the run, the preset filling those left at their default.
    settings = {**ctx.params, **apply_preset(ctx, preset)}

    conf = Config(
        input_format=settings["input_format"],
        force_unlock=settings["force_unlock"],
        raw_headers=settings["raw_headers"],
        hash_headers=settings["hash_headers"],
        minimal_headers=min(DEFAULT_MINIMAL_HEADERS, len(settings["hash_headers"])),
        hash_body=settings["hash_body"],
        hash_only=settings["hash_only"],
        # An explicit database location is a request to use it.
        cache=settings["cache"] or settings["cache_path"] is not None,
        cache_path=settings["cache_path"],
        size_threshold=settings["size_threshold"],
        content_threshold=settings["content_threshold"],
        show_diff=settings["show_diff"],
        strategies=settings["strategies"],
        time_source=settings["time_source"],
        regexp=settings["regexp"],
        action=settings["action"],
        export=settings["export"],
        export_format=settings["export_format"],
        export_append=settings["export_append"],
        hardlink_differing=settings["hardlink_differing"],
        dry_run=settings["dry_run"],
    )

    dedup = Deduplicate(conf)
    # A run cut short by an error or an interrupt never reaches `close_all()` below.
    # Unlock its boxes on the way out anyway, or the next run finds them locked.
    ctx.call_on_close(lambda: dedup.close_all(flush=False))

    # The hashing and selection steps set aside the mails an unexpected error hits,
    # and report them at the end. An error escaping the steps ends the run here,
    # with a one-line message or a bug report.
    with report_unexpected_errors(dedup):
        echo_step("Step #1 - Load mails")
        with step_progressbar(
            iterable=mail_sources,
            length=len(mail_sources),
            label="Mail sources",
            show_pos=True,
        ) as progress:
            for source in progress:
                dedup.add_source(source)

        echo_step("Step #2 - Compute hashes and group duplicates")
        dedup.hash_all()

        if conf["hash_only"]:
            ignored_user_options = ignored_step_options(ctx)
            if ignored_user_options:
                logging.warning(
                    "Options provided by user, but ignored in -H/--hash-only mode: "
                    + ", ".join(ignored_user_options)
                )

            # Print all computed hashes. Rendering the canonical headers needs the
            # full message back, so borrow it one mail at a time to keep memory flat.
            for all_mails in dedup.mails.values():
                for mail in all_mails:
                    with mail.hydrated():
                        echo(mail.pretty_canonical_headers())
                        echo(f"Hash: {mail.hash_key()}")

            # Exit right away, releasing the boxes and the cache on the way out.
            dedup.close_all()
            ctx.exit(1 if dedup.report_failures() else 0)

        echo_step("Step #3 - Select mails in each group")
        dedup.build_sets()

        echo_step("Step #4 - Perform action on selected mails")
        conf["action"].perform(dedup)
        dedup.close_all()

        echo_step("Step #5 - Report and statistics")
        # Print deduplication statistics, then performs a self-check on them.
        echo(dedup.report())
        failed = dedup.report_failures()
        dedup.check_stats()

    if failed:
        ctx.exit(1)
