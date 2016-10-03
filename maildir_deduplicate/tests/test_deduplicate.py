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

import unittest
from os import makedirs, path
from textwrap import dedent
from email.utils import formatdate as maildate

import arrow

from maildir_deduplicate import MD_SUBDIRS, PY3
from maildir_deduplicate.cli import cli

from .test_cli import CLITestCase


if PY3:
    basestring = (str, bytes)


class MailFactory(object):

    """ Create fake mail messages to serve as unittest fixtures.

    Help production of either random, customized or deterministic mail message.
    """

    def __init__(self, **custom_fields):
        """ Init the mail with custom fields. """
        # Defaults fields values.
        self.fields = {
            'body': "Да, они летят.",
            'date': arrow.utcnow()}

        # Check all custom fields are recognized and supported.
        assert set(custom_fields).issubset(self.fields)

        # Parse dates and normalize to Arrow instance.
        if 'date' in custom_fields:
            custom_fields['date'] = arrow.get(custom_fields['date'])

        # Update default values with custom ones.
        self.fields.update(custom_fields)

        # Add an extra rendered string in RFC2882 format.
        self.fields['date_rfc2822'] = maildate(
            self.fields['date'].float_timestamp)

    def render(self):
        """ Returns the full, rendered content of the mail. """
        return dedent("""\
            Return-path: <none@nohost.com>
            Envelope-to: me@host.com
            Delivery-date: {date_rfc2822}
            Received: from [11.11.11.11] (helo=nope.com)
            \tby host.com with esmtp (Exim 4.80)
            \t(envelope-from <noone@nohost.com>)
            \tid 1CX8OJ-0014c9-Ii
            \tfor me@host.com; {date_rfc2822}
            Date: {date_rfc2822}
            From: foo@bar.com
            Message-Id: <201111231111.abcdef101@mail.nohost.com>
            To: baz
            Subject: A duplicate mail
            Mime-Version: 1.0
            Content-Length: 60
            Content-Type: text/plain; charset="utf-8"
            Content-Transfer-Encoding: 8bit
            {body}""".format(**self.fields)).encode('utf-8')

    def save(self, filepath):
        """ Save the mail to the filesystem. """
        with open(filepath, 'wb') as mail_file:
            mail_file.write(self.render())
        # TODO: find a way to set ctime here so we can test for time-based
        # deduplication strategies.


class TestDeduplicate(CLITestCase):

    @staticmethod
    def fake_maildir(mails, md_path):
        """ Create a fake maildir and populate it with mails.

        TODO: wrap click's isolated_filesystem() context manager.
        """
        # Create maildir structure.
        for subdir in MD_SUBDIRS:
            makedirs(path.join(md_path, subdir))

        # Populate the 'cur' sub-folder with provided mails.
        for filename, fake_mail in mails.items():
            filepath = path.join(md_path, 'cur', filename)
            assert isinstance(fake_mail, MailFactory)
            fake_mail.save(filepath)


class TestDryRun(TestDeduplicate):

    maildir_path = './dry_run'

    small_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
    medium_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş. ++")
    big_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++")

    mails = {
        'mail0:1,S': small_mail,
        'mail1:1,S': big_mail,
        'mail2:1,S': small_mail,
        'mail3:1,S': medium_mail,
        'mail4:1,S': medium_mail,
        'mail5:1,S': big_mail}

    def test_maildir_smaller_strategy_dry_run(self):
        """ Check nothing is removed in dry-run mode. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=delete-smaller', '--dry-run',
                self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            for mail_id in self.mails.keys():
                self.assertTrue(
                    path.isfile(path.join(self.maildir_path, 'cur', mail_id)))


class TestSizeStrategy(TestDeduplicate):

    maildir_path = './strategy_smaller'

    small_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş.")
    medium_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş. ++")
    big_mail = MailFactory(
        body="Hello I am a duplicate mail. With annoying ćĥäŖş. +++++")

    mails = {
        'mail0:1,S': small_mail,
        'mail1:1,S': big_mail,
        'mail2:1,S': small_mail,
        'mail3:1,S': medium_mail,
        'mail4:1,S': medium_mail,
        'mail5:1,S': big_mail}

    def test_maildir_smaller_strategy(self):
        """ Test strategy of smaller mail deletion. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=delete-smaller', self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            # Biggest mails are kept but not the smaller ones.
            kept = ['mail1:1,S', 'mail5:1,S']
            deleted = ['mail0:1,S', 'mail2:1,S', 'mail3:1,S', 'mail4:1,S']

            for mail_id in kept:
                self.assertTrue(path.isfile(path.join(
                    self.maildir_path, 'cur', mail_id)))
            for mail_id in deleted:
                self.assertFalse(path.isfile(path.join(
                    self.maildir_path, 'cur', mail_id)))


class TestDateStrategy(TestDeduplicate):

    maildir_path = './strategy_date'

    newest_date = arrow.utcnow()
    newer_date = newest_date.replace(minutes=-1)
    older_date = newest_date.replace(hours=-2)
    oldest_date =  newest_date.replace(days=-3)

    newest_mail = MailFactory(date=newest_date)
    newer_mail = MailFactory(date=newer_date)
    older_mail = MailFactory(date=older_date)
    oldest_mail = MailFactory(date=oldest_date)

    mails = {
        'mail0:1,S': oldest_mail,
        'mail1:1,S': newest_mail,
        'mail2:1,S': oldest_mail,
        'mail3:1,S': newer_mail,
        'mail4:1,S': older_mail,
        'mail5:1,S': older_mail,
        'mail6:1,S': newer_mail,
        'mail7:1,S': newest_mail}

    @unittest.skip("Date-based deduplication tests needs us to set ctime.")
    def test_maildir_older_strategy(self):
        """ Test strategy of older mail deletion. """
        with self.runner.isolated_filesystem():
            self.fake_maildir(
                mails=self.mails,
                md_path=self.maildir_path)

            result = self.runner.invoke(cli, [
                'deduplicate', '--strategy=delete-older', self.maildir_path])

            self.assertEqual(result.exit_code, 0)

            # Newest mails are kept but not the older ones.
            kept = ['mail1:1,S', 'mail7:1,S']
            deleted = [
                'mail0:1,S', 'mail2:1,S', 'mail3:1,S', 'mail4:1,S',
                'mail5:1,S', 'mail6:1,S']

            for mail_id in kept:
                self.assertTrue(path.isfile(path.join(
                    self.maildir_path, 'cur', mail_id)))
            for mail_id in deleted:
                self.assertFalse(path.isfile(path.join(
                    self.maildir_path, 'cur', mail_id)))
