#!/usr/bin/env python
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

import codecs
import os
import re

from setuptools import setup, find_packages


MODULE_NAME = 'maildir_deduplicate'


def get_version():

    with open(os.path.join(
        os.path.dirname(__file__), MODULE_NAME, '__init__.py')
    ) as init:

        for line in init.readlines():
            res = re.match(r'__version__ *= *[\'"]([0-9a-z\.]*)[\'"]$', line)
            if res:
                return res.group(1)


def get_long_description():
    readme = os.path.join(os.path.dirname(__file__), 'README.rst')
    changes = os.path.join(os.path.dirname(__file__), 'CHANGES.rst')
    return codecs.open(readme, encoding='utf-8').read() + '\n' + \
        codecs.open(changes, encoding='utf-8').read()


setup(
    name='maildir-deduplicate',
    version=get_version(),
    description="Deduplicate mails from a set of maildir folders.",
    long_description=get_long_description(),

    author='Kevin Deldycke',
    author_email='kevin@deldycke.com',
    url='https://github.com/kdeldycke/maildir-deduplicate',
    license='GPLv2+',

    install_requires=[
        'click >= 5.0',
    ],

    packages=find_packages(),

    tests_require=[],
    test_suite=MODULE_NAME + '.tests',

    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: '
        'GNU General Public License v2 or later (GPLv2+)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Topic :: Communications :: Email',
        'Topic :: Utilities',
    ],

    entry_points={
        'console_scripts': [
            'mdedup=maildir_deduplicate.cli:cli',
        ],
    }
)
