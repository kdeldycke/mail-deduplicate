#!/usr/bin/env python
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

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals
)

import io
import re
from os import path

from setuptools import find_packages, setup

MODULE_NAME = 'maildir_deduplicate'
PACKAGE_NAME = MODULE_NAME.replace('_', '-')

DEPENDENCIES = [
    'boltons >= 16.3.0',
    'click >= 5.0',
    'click_log >= 0.2.0, < 0.3.0',
    'progressbar2',
    'tabulate',
]

EXTRA_DEPENDENCIES = {
    # Extra dependencies are made available through the
    # `$ pip install .[keyword]` command.
    'docs': [
        'sphinx >= 1.4',
        'sphinx_rtd_theme'],
    'tests': [
        'arrow',
        'coverage',
        'nose',
        'pycodestyle >= 2.1.0',
        'pylint'],
    'develop': [
        'bumpversion',
        'isort',
        'readme_renderer >= 16.0',
        'setuptools >= 24.2.1'
        'wheel'],
}


def read_file(*relative_path_elements):
    """ Return content of a file relative to this ``setup.py``. """
    file_path = path.join(path.dirname(__file__), *relative_path_elements)
    return io.open(file_path, encoding='utf8').read().strip()


# Cache fetched version.
_version = None  # noqa


def version():
    """ Extracts version from the ``__init__.py`` file at the module's root.

    Inspired by: https://packaging.python.org/single_source_version/
    """
    global _version
    if _version:
        return _version
    init_file = read_file(MODULE_NAME, '__init__.py')
    matches = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', init_file, re.M)
    if not matches:
        raise RuntimeError("Unable to find version string in __init__.py .")
    _version = matches.group(1)  # noqa
    return _version


def latest_changes():
    """ Extract part of changelog pertaining to version. """
    lines = []
    for line in read_file('CHANGES.rst').splitlines():
        if line.startswith('-------'):
            if len(lines) > 1:
                lines = lines[:-1]
                break
        if lines:
            lines.append(line)
        elif line.startswith("`{} (".format(version())):
            lines.append(line)
    if not lines:
        raise RuntimeError(
            "Unable to find changelog for the {} release.".format(version()))
    # Renormalize and clean lines.
    return '\n'.join(lines).strip().split('\n')


def long_description():
    """ Collates project README and latest changes. """
    changes = latest_changes()
    changes[0] = "`Changes for v{}".format(changes[0][1:])
    changes[1] = '-' * len(changes[0])
    return "\n\n\n".join([
        read_file('README.rst'),
        '\n'.join(changes),
        "`Full changelog <https://{}.readthedocs.io/en/develop/changelog.html"
        "#changelog>`_.".format(PACKAGE_NAME),
    ])


setup(
    name=PACKAGE_NAME,
    version=version(),
    description="Deduplicate mails from a set of maildir folders.",
    long_description=long_description(),
    keywords=['CLI', 'mail', 'email', 'maildir', 'deduplicate'],

    author='Kevin Deldycke',
    author_email='kevin@deldycke.com',
    url='https://github.com/kdeldycke/maildir-deduplicate',
    license='GPLv2+',

    packages=find_packages(),
    # https://www.python.org/dev/peps/pep-0345/#version-specifiers
    python_requires='>= 2.7, != 3.0, != 3.1, != 3.2',
    install_requires=DEPENDENCIES,
    tests_require=DEPENDENCIES + EXTRA_DEPENDENCIES['tests'],
    extras_require=EXTRA_DEPENDENCIES,
    dependency_links=[
    ],
    test_suite='{}.tests'.format(MODULE_NAME),

    classifiers=[
        # See: https://pypi.python.org/pypi?:action=list_classifiers
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: '
        'GNU General Public License v2 or later (GPLv2+)',
        'Operating System :: OS Independent',
        # List of python versions and their support status:
        # https://en.wikipedia.org/wiki/CPython#Version_history
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Communications :: Email',
        'Topic :: Utilities',
    ],

    entry_points={
        'console_scripts': [
            'mdedup={}.cli:cli'.format(MODULE_NAME),
        ],
    }
)
