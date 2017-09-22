# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2017 Kevin Deldycke <kevin@deldycke.com>
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

import unittest

from boltons.tbutils import ExceptionInfo
from click.testing import CliRunner

from ..cli import cli


class CLITestCase(unittest.TestCase):

    """ Utilities and helpers to easely write unit-tests. """

    def setUp(self):
        self.runner = CliRunner()

    def invoke(self, *args):
        """ Executes CLI, print output and return results. """
        result = self.runner.invoke(cli, args)

        # Simulate CLI output.
        print("$ mdedupe {}".format(' '.join(args)))
        print(result.output)

        # Print some more debug info.
        print(result)
        if result.exception:
            print(ExceptionInfo.from_exc_info(
                *result.exc_info).get_formatted())

        return result
