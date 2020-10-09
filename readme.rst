Mail Deduplicate
================

Command-line tool to deduplicate mails from a set of mbox files and/or maildir
folders.

Stable release: |release| |versions|

Development: |build| |docs| |coverage|

.. |release| image:: https://img.shields.io/pypi/v/mail-deduplicate.svg
    :target: https://pypi.python.org/pypi/mail-deduplicate
    :alt: Last release
.. |versions| image:: https://img.shields.io/pypi/pyversions/mail-deduplicate.svg
    :target: https://pypi.python.org/pypi/mail-deduplicate
    :alt: Python versions
.. |build| image:: https://github.com/kdeldycke/mail-deduplicate/workflows/Tests/badge.svg
    :target: https://github.com/kdeldycke/mail-deduplicate/actions?query=workflow%3ATests
    :alt: Unittests status
.. |docs| image:: https://readthedocs.org/projects/mail-deduplicate/badge/?version=develop
    :target: https://mail-deduplicate.readthedocs.io/en/develop/
    :alt: Documentation Status
.. |coverage| image:: https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/develop/graph/badge.svg
    :target: https://codecov.io/github/kdeldycke/mail-deduplicate?branch=develop
    :alt: Coverage Status


Features
--------

* Duplicate detection based on cherry-picked mail headers.
* Source mails from multiple mbox files and/or maildir folders.
* Multiple removal strategies based on size, timestamp or file path.
* Dry-run mode.
* Protection against false-positives by checking for size and content
  differences.


Installation
------------

This package is `available on PyPi
<https://pypi.python.org/pypi/mail-deduplicate>`_, so you can install the
latest stable release and its dependencies with a simple ``pip`` call:

.. code-block:: shell-session

    $ pip install mail-deduplicate


Documentation
-------------

Docs are `hosted on Read the Docs
<https://maildir-deduplicate.readthedocs.io>`_.
