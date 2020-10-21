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

""" Utilities to manage colors. """

import re
from functools import partial

import click
from click_log.core import ColorFormatter

from . import CLI_NAME, logger


# Help screen and log message colors.
# Available options: https://click.palletsprojects.com/en/master/api/#click.style
colors = {
    "cli": dict(fg="bright_white"),
    "title": dict(fg="bright_green", bold=True),
    "subtitle": dict(fg="green"),
    "option": dict(fg="cyan"),
    "choice": dict(fg="magenta"),
    "metavar": dict(fg="bright_black"),
}

# Update with default log message colors.
assert set(colors).isdisjoint(ColorFormatter.colors)
colors.update(ColorFormatter.colors)


# Reverse color mapping to detect overlapping colors.
color_index = {}
for category, color_params in colors.items():
    color_index.setdefault(tuple(sorted(color_params.items())), set()).add(category)
for color_params, categories in color_index.items():
    if len(categories) > 1:
        logger.debug(f"{categories!r} shares the same {color_params!r} colors.")


# Create handy function shortcuts for each class of colorization.
for color_category, color_params in colors.items():
    globals()[f"{color_category}_style"] = partial(click.style, **color_params)


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


def colorized_help(help_txt, keywords):
    """Get default help screen and colorize section titles, options and choice
    keywords."""
    options, choices, metavars = keywords

    def colorize(match, **kwargs):
        """Re-create the matching string by concatenating all groups, but only
        colorize named groups.
        """
        txt = ""
        for group in match.groups():
            if group in match.groupdict().values():
                txt += click.style(group, **kwargs)
            else:
                txt += group
        return txt

    # Highligh numbers.
    help_txt = re.sub(
        r"(\s)(?P<colorize>-?\d+)", partial(colorize, **colors["choice"]), help_txt
    )

    # Highlight CLI.
    help_txt = re.sub(
        fr"(\s)(?P<colorize>{CLI_NAME})", partial(colorize, **colors["cli"]), help_txt
    )

    # Highligh sections.
    help_txt = re.sub(
        r"^(?P<colorize>\S[\S+ ]+)(:)",
        partial(colorize, **colors["title"]),
        help_txt,
        flags=re.MULTILINE,
    )

    # Highlight keywords.
    for matching_keywords, color in [
        (sorted(options), colors["option"]),
        (sorted(choices, reverse=True), colors["choice"]),
        (sorted(metavars, reverse=True), colors["metavar"]),
    ]:
        for keyword in matching_keywords:
            # Accounts for text wrapping after a dash.
            keyword = keyword.replace("-", "-\\s*")
            help_txt = re.sub(
                fr"([\s\[\|\(])(?P<colorize>{keyword})",
                partial(colorize, **color),
                help_txt,
            )

    return help_txt
