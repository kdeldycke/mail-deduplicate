# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2016 Kevin Deldycke <kevin@deldycke.com>
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

from __future__ import absolute_import, division, print_function

import textwrap
import unittest
from copy import deepcopy
from os import path

from maildir_deduplicate import Deduplicate, logger


class TestDeduplicate(unittest.TestCase):
    default_args = {
        "strategy": "smaller",
        "regexp": None,
        "dry_run": True,
        "show_diffs": False,
        "use_message_id": False,
        "size_threshold": 512,
        "diff_threshold": 512,
        "progress": False,
    }

    mails = {
        "bigger": "mail1:1,S",
        "smaller": "mail0:1,S",
    }

    def message_factory(self):
        return textwrap.dedent("""\
            From: foo@bar.com
            To: báz
            Subject: Maintenant je vous présente mon collègue, le pouf célèbre
            \tJean de Baddie
            Mime-Version: 1.0
            Content-Type: text/plain; charset="utf-8"
            Content-Transfer-Encoding: 8bit
            Да, они летят.
            """).encode('utf-8')

    def do_maildir_test_strategies(self, dedup_kwargs, keptfile, mdir=None):
        if mdir is None:
            mdir = path.join(path.dirname(__file__), "testdata/maildir_dups")
        dedup = Deduplicate(**dedup_kwargs)
        dedup.add_maildir(mdir)
        dedup.run()

        # Check that keptfile is kept.
        self.assertTrue(path.isfile(path.join(mdir, "cur", keptfile)))

    def get_args(self, **kwargs):
        '''Gets a copy of the defaults and updates with any kwargs given'''
        args = deepcopy(self.default_args)
        for k, v in kwargs.items():
            args[k] = v
        return args

    def test_maildir_smaller(self):
        args = self.get_args(strategy="smaller")
        self.do_maildir_test_strategies(args, self.mails["bigger"])
