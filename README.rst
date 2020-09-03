Maildir Deduplicate
===================


.. DANGER::
   This is an **old version**. The project has been renamed to *Mail
   Deduplicate* and is now available on:
   
   * Github at https://github.com/kdeldycke/mail-deduplicate
   * PyPi at https://pypi.org/project/mail-deduplicate



Command-line tool to deduplicate mails from a set of maildir folders.

Stable release: |release| |versions| |license| |dependencies|

Development: |build| |docs| |coverage| |quality|

.. |release| image:: https://img.shields.io/pypi/v/maildir-deduplicate.svg
    :target: https://pypi.python.org/pypi/maildir-deduplicate
    :alt: Last release
.. |versions| image:: https://img.shields.io/pypi/pyversions/maildir-deduplicate.svg
    :target: https://pypi.python.org/pypi/maildir-deduplicate
    :alt: Python versions
.. |license| image:: https://img.shields.io/pypi/l/maildir-deduplicate.svg
    :target: https://www.gnu.org/licenses/gpl-2.0.html
    :alt: Software license
.. |dependencies| image:: https://requires.io/github/kdeldycke/maildir-deduplicate/requirements.svg?branch=master
    :target: https://requires.io/github/kdeldycke/maildir-deduplicate/requirements/?branch=master
    :alt: Requirements freshness
.. |build| image:: https://travis-ci.org/kdeldycke/maildir-deduplicate.svg?branch=develop
    :target: https://travis-ci.org/kdeldycke/maildir-deduplicate
    :alt: Unit-tests status
.. |docs| image:: https://readthedocs.org/projects/maildir-deduplicate/badge/?version=develop
    :target: https://maildir-deduplicate.readthedocs.io/en/develop/
    :alt: Documentation Status
.. |coverage| image:: https://codecov.io/gh/kdeldycke/maildir-deduplicate/branch/develop/graph/badge.svg
    :target: https://codecov.io/github/kdeldycke/maildir-deduplicate?branch=develop
    :alt: Coverage Status
.. |quality| image:: https://scrutinizer-ci.com/g/kdeldycke/maildir-deduplicate/badges/quality-score.png?b=develop
    :target: https://scrutinizer-ci.com/g/kdeldycke/maildir-deduplicate/?branch=develop
    :alt: Code Quality


Features
--------

* Duplicate detection based on cherry-picked mail headers.
* Source mails from multiple maildirs.
* Multiple removal strategies based on size, timestamp or file path.
* Dry-run mode.
* Protection against false-positives by checking for size and content
  differences.


Installation
------------

This package is `available on PyPi
<https://pypi.python.org/pypi/maildir-deduplicate>`_, so you can install the
latest stable release and its dependencies with a simple ``pip`` call:

.. code-block:: shell-session

    $ pip install maildir-deduplicate


Documentation
-------------

Docs are `hosted on Read the Docs
<https://maildir-deduplicate.readthedocs.io>`_.
