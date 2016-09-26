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

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals
)

from os import makedirs, path
from textwrap import dedent

from maildir_deduplicate import MD_SUBDIRS, PY3
from maildir_deduplicate.cli import cli

from .test_cli import CLITestCase

if PY3:
    basestring = (str, bytes)


class TestDeduplicate(CLITestCase):

    @staticmethod
    def message_factory(**custom_fields):
        """ Produce a random or customized mail message. """
        # Defaults fields values.
        fields = {
            'body': "Да, они летят.",
            'date': "Fri, 11 Nov 2011 23:11:11 +1100"
        }

        # Check all custom fields are recognized and in the expected format.
        assert set(custom_fields).issubset(fields)
        for value in custom_fields.values():
            assert isinstance(value, basestring)

        # Update default values with custom ones.
        fields.update(custom_fields)

        return dedent("""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: {date}
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; {date}
            Date: {date}
            From: foo@bar.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: báz
            Subject: Maintenant je vous présente mon collègue, le pouf célèbre
            \tJean de Baddie
            Mime-Version: 1.0
            Content-Length: 60
            Content-Type: text/plain; charset="utf-8"
            Content-Transfer-Encoding: 8bit
            {body}""".format(**fields)).encode('utf-8')

    @staticmethod
    def fake_maildir(mails, md_path):
        """ Create a fake maildir and populate it with mails.

        TODO: wrap click's isolated_filesystem() context manager.
        """
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

    small_mail = TestDeduplicate.message_factory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
    big_mail = TestDeduplicate.message_factory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş.\nEOM")

    mails = {
        'mail0:1,S': small_mail,
        'mail1:1,S': big_mail,
        'mail2:1,S': small_mail}

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

    new_mail = TestDeduplicate.message_factory(
        date="Wed, 31 Aug 2016 23:10:12 -0000")
    old_mail = TestDeduplicate.message_factory(
        date="Wed, 31 Aug 2016 21:59:16 -0000")

    mails = {
        'mail0:1,S': new_mail,
        'mail1:1,S': old_mail,
        'mail2:1,S': new_mail}

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

            # Oldest mail is kept but not the newer ones.
            self.assertTrue(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail1:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail0:1,S')))
            self.assertFalse(
                path.isfile(path.join(self.maildir_path, 'cur', 'mail2:1,S')))
