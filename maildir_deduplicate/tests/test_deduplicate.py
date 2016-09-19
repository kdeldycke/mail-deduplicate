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

from textwrap import dedent
from os import path, makedirs

from maildir_deduplicate import MD_SUBDIRS
from maildir_deduplicate.cli import cli

from .test_cli import CLITestCase


class TestDeduplicate(CLITestCase):

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

    def fake_maildir(self, mails, md_path):
        """ Create a fake maildir and populate it with mails. """
        # Create maildir structure.
        for subdir in MD_SUBDIRS:
            makedirs(path.join(md_path, subdir))

        # Populate the 'cur' sub-folder with provided mails.
        for filename, content in mails.items():
            filepath = path.join(md_path, 'cur', filename)
            with open(filepath, 'wb') as mail_file:
                mail_file.write(content)


class TestSizeStrategy(TestDeduplicate):

    maildir_path = './strategy_smaller'

    mails = {
        # Small mail #1.
        'mail0:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Fri, 11 Nov 2011 23:11:11 +1100
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Fri, 11 Nov 2011 23:11:11 +1100
            Date: Fri, 11 Nov 2011 23:11:11 +1100
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate mail. With annoying ćĥäŖş.
            """).encode('utf-8'),
        # Big mail.
        'mail1:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Fri, 11 Nov 2011 23:11:11 +1100
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Fri, 11 Nov 2011 23:11:11 +1100
            Date: Fri, 11 Nov 2011 23:11:11 +1100
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate mail. With annoying ćĥäŖş.

            EOM
            """).encode('utf-8'),
        # Small mail #2.
        'mail2:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Fri, 11 Nov 2011 23:11:11 +1100
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Fri, 11 Nov 2011 23:11:11 +1100
            Date: Fri, 11 Nov 2011 23:11:11 +1100
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate Mail. With annoying ćĥäŖş.
            """).encode('utf-8'),
    }

    def test_maildir_smaller_strategy_dry_run(self):
        """ Check nothing is removed in dry-run mode. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=smaller', '--dry-run',
                self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            for filename in self.mails.keys():
                self.assertTrue(
                    path.isfile(path.join(self.maildir_path, 'cur', filename)))

    def test_maildir_smaller_strategy(self):
        """ Test strategy of smaller mail deletion for real. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=smaller', self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            # Biggest mail is kept but not the smaller ones.
            self.assertTrue(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail1:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail0:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail2:1,S')))


class TestDateStrategy(TestDeduplicate):

    maildir_path = './strategy_date'

    mails = {
        # New mail #1.
        'mail0:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Wed, 31 Aug 2016 23:10:12 -0000
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Wed, 31 Aug 2016 23:10:12 -0000
            Date: Wed, 31 Aug 2016 23:10:12 -0000
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate mail. With annoying ćĥäŖş.
            """).encode('utf-8'),
        # Old mail.
        'mail1:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Wed, 31 Aug 2016 21:59:16 -0000
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Wed, 31 Aug 2016 21:59:16 -0000
            Date: Wed, 31 Aug 2016 21:59:16 -0000
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate mail. With annoying ćĥäŖş.
            """).encode('utf-8'),
        # New mail #2.
        'mail2:1,S': dedent(u"""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: Wed, 31 Aug 2016 23:10:12 -0000
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; Wed, 31 Aug 2016 23:10:12 -0000
            Date: Wed, 31 Aug 2016 23:10:12 -0000
            From: none@nohost.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: me@host.com
            Subject: A duplicate mail
            Content-Length: 60

            Hello I am a duplicate mail. With annoying ćĥäŖş.
            """).encode('utf-8'),
    }

    def test_maildir_newer_strategy_dry_run(self):
        """ Check nothing is removed in dry-run mode. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=newer', '--dry-run',
                self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            for filename in self.mails.keys():
                self.assertTrue(
                    path.isfile(path.join(self.maildir_path, 'cur', filename)))

    def test_maildir_newer_strategy(self):
        """ Test strategy of newer mail deletion for real. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=newer', self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            import pdb; pdb.set_trace()  # XXX BREAKPOINT

            # Oldest mail is kept but not the newer ones.
            self.assertTrue(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail1:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail0:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail2:1,S')))
