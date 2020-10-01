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

from textwrap import indent

import click
import pytest
from boltons.iterutils import flatten, same
from boltons.strutils import strip_ansi
from boltons.tbutils import ExceptionInfo
from click.testing import CliRunner

from ..cli import mdedup
from .. import CLI_NAME

""" Fixtures, configuration and helpers for tests. """


def print_cli_output(cmd, output):
    """ Simulate CLI output. Used to print debug traces in test results. """
    print("\n► {}".format(click.style(" ".join(cmd), fg="white")))
    if output:
        print(indent(output, "  "))


@pytest.fixture
def runner():
    runner = CliRunner(mix_stderr=False)
    with runner.isolated_filesystem():
        yield runner


@pytest.fixture
def invoke(runner):
    """ Executes Click's CLI, print output and return results. """

    def _run(*args, color=False):
        # We allow for nested iterables and None values as args for
        # convenience. We just need to flatten and filters them out.
        args = list(filter(None.__ne__, flatten(args)))
        if args:
            assert same(map(type, args), str)

        result = runner.invoke(mdedup, args, color=color)

        # Strip colors out of results.
        result.stdout_bytes = strip_ansi(result.stdout_bytes)
        result.stderr_bytes = strip_ansi(result.stderr_bytes)

        print_cli_output([CLI_NAME] + args, result.output)

        # Print some more debug info.
        print(result)
        if result.exception:
            print(ExceptionInfo.from_exc_info(*result.exc_info).get_formatted())

        return result

    return _run
