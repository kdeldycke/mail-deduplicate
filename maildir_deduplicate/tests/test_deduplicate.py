# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2016 Kevin Deldycke <kevin@deldycke.com>
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

from __future__ import absolute_import, division, print_function

import textwrap
import unittest
from copy import deepcopy
from os import path

from maildir_deduplicate import logger
from maildir_deduplicate.deduplicate import Deduplicate


class TestDeduplicate(unittest.TestCase):
    default_args = {
        'strategy': 'smaller',
        'regexp': None,
        'dry_run': True,
        'show_diffs': False,
        'use_message_id': False,
        'size_threshold': 512,
        'diff_threshold': 512,
        'progress': False}

    maildir_path = None

    def message_factory(self):
        """ Building block for future fuzzing and dynamic content creation. """
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

    def run_maildir_test(
            self, dedup_kwargs, kept_files=None, removed_files=None):
        """ Run the deduplication and check for removed and kept files. """
        assert self.maildir_path
        maildir = path.join(path.dirname(__file__), self.maildir_path)

        dedup = Deduplicate(**dedup_kwargs)
        dedup.add_maildir(maildir)
        dedup.run()

        # Check files that should be kept are still there.
        if kept_files:
            assert isinstance(kept_files, list)
            for filename in kept_files:
                self.assertTrue(
                    path.isfile(path.join(maildir, 'cur', filename)))

        # Check files that should be removed were deleted.
        if removed_files:
            assert isinstance(removed_files, list)
            for filename in removed_files:
                self.assertFalse(
                    path.isfile(path.join(maildir, 'cur', filename)))

    def get_args(self, **kwargs):
        """ Gets a copy of the defaults and updates with any kwargs given. """
        args = deepcopy(self.default_args)
        args.update(kwargs)
        return args


class TestSizeStrategy(TestDeduplicate):

    maildir_path = 'testdata/maildir_dups'

    mails = {
        'bigger': 'mail1:1,S',
        'smaller': 'mail0:1,S'}

    def test_maildir_smaller_strategy_dry_run(self):
        args = self.get_args(strategy='smaller')
        self.run_maildir_test(
            args,
            kept_files=[self.mails['bigger'], self.mails['smaller']])

    @unittest.skip("TODO: find a way to resurect initial test data.")
    def test_maildir_smaller_strategy(self):
        args = self.get_args(strategy='smaller', dry_run=False)
        self.run_maildir_test(
            args,
            kept_files=[self.mails['bigger']],
            removed_files=[self.mails['smaller']])
