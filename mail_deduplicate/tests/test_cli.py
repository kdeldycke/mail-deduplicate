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
from pathlib import Path

import pytest

from .. import __version__, logger


def test_real_fs():
    """Check a simple test is not caught into the CLI runner fixture which is
    encapsulating all filesystem access into temporary directory structure."""
    assert str(Path(__file__)).startswith(str(Path.cwd()))


def test_temporary_fs(runner):
    """Check the CLI runner fixture properly encapsulated the filesystem in
    temporary directory."""
    assert not str(Path(__file__)).startswith(str(Path.cwd()))


def test_bare_call(invoke):
    result = invoke()
    assert result.exit_code == 0
    assert "Usage: " in result.output


def test_main_help(invoke):
    result = invoke("--help")
    assert result.exit_code == 0
    assert "Usage: " in result.output


def test_version(invoke):
    result = invoke("--version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_unknown_option(invoke):
    result = invoke("--blah")
    assert result.exit_code == 2
    assert "Error: no such option: --blah" in result.output


def test_unrecognized_verbosity(invoke):
    result = invoke("--verbosity", "random")
    assert result.exit_code == 2
    assert "Error: Invalid value for '--verbosity' / '-v'" in result.output


@pytest.mark.parametrize("level", ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"])
def test_verbosity(invoke, level):
    result = invoke("--verbosity", level)
    assert result.exit_code == 0
    assert "Usage: " in result.output

    assert logger.level == getattr(logging, level)
    if level == "DEBUG":
        assert "debug: " in result.output
    else:
        assert "debug: " not in result.output
