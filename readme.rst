Mail Deduplicate
================

Command-line tool to deduplicate mails from a set of boxes.

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

.. figure:: https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/develop/docs/cli-coloured-header.png
    :align: center


Features
--------

* Duplicate detection based on cherry-picked and normalized mail headers.
* Source and deduplicate mails from multiple sources.
* Reads and writes to ``mbox``, ``maildir``, ``babyl``, ``mh`` and ``mmdf`` formats.
* Multiple duplicate selection strategies based on size, content, timestamp, file
  path or random choice.
* Copy, move or delete the resulting set of mails after the deduplication.
* Dry-run mode.
* Protection against false-positives by checking for size and content
  differences.


Screenshots
-----------

.. figure:: https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/develop/docs/cli-colored-help.png
    :align: center

.. figure:: https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/develop/docs/cli-coloured-run.png
    :align: center


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
<https://mail-deduplicate.readthedocs.io>`_.
