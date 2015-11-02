# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2015 Kevin Deldycke <kevin@deldycke.com>
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

import textwrap
import unittest

from maildir_deduplicate import Deduplicate


class TestDeduplicate(unittest.TestCase):

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


    #def test_simple_dedup(self):
    #    msg1 =
    #    msg2 =

    #    dedup = Deduplicate()
    #    dedup.add_message(msg1)
    #    dedup.add_message(msg2)

    #    dedup.run()
