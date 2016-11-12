Maildir Deduplicate
===================

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
.. |dependencies| image:: https://img.shields.io/requires/github/kdeldycke/maildir-deduplicate/master.svg
    :target: https://requires.io/github/kdeldycke/maildir-deduplicate/requirements/?branch=master
    :alt: Requirements freshness
.. |build| image:: https://img.shields.io/travis/kdeldycke/maildir-deduplicate/develop.svg
    :target: https://travis-ci.org/kdeldycke/maildir-deduplicate
    :alt: Unit-tests status
.. |docs| image:: https://readthedocs.org/projects/maildir-deduplicate/badge/?version=develop
    :target: http://maildir-deduplicate.readthedocs.io/en/develop/
    :alt: Documentation Status
.. |coverage| image:: https://codecov.io/github/kdeldycke/maildir-deduplicate/coverage.svg?branch=develop
    :target: https://codecov.io/github/kdeldycke/maildir-deduplicate?branch=develop
    :alt: Coverage Status
.. |quality| image:: https://img.shields.io/scrutinizer/g/kdeldycke/maildir-deduplicate.svg
    :target: https://scrutinizer-ci.com/g/kdeldycke/maildir-deduplicate/?branch=develop
    :alt: Code Quality


Install
-------

This package is `available on PyPi
<https://pypi.python.org/pypi/maildir-deduplicate>`_, so you can install the
latest stable release and its dependencies with a simple `pip` call:

.. code-block:: bash

    $ pip install maildir-deduplicate

See also `pip installation instructions
<https://pip.pypa.io/en/stable/installing/>`_.


Usage
-----

List global options and commands:

.. code-block::

    $ mdedup --help
    Usage: mdedup [OPTIONS] COMMAND [ARGS]...

      CLI for maildirs content analysis and deletion.

    Options:
      --version      Show the version and exit.
      -v, --verbose  Print much more debug statements.
      --help         Show this message and exit.

    Commands:
      deduplicate  Deduplicate maildirs content.
      hash         Hash a single mail.


Deduplication command specific options:

.. code-block:: bash

    $ mdedup deduplicate --help
    Usage: mdedup deduplicate [OPTIONS] [MAILDIRS]...

      Deduplicate mails from a set of maildir folders.

      Removal strategies for each set of mail duplicates:
          - older: remove all but the newest message (determined by ctime).
          - newer: remove all but the oldest message (determined by ctime).
          - smaller: Remove all but largest message.
          - matching: Remove duplicates whose file path matches the regular
            expression provided via the --regexp parameter.
          - not-matching: Remove duplicates whose file path does not match the
            regular expression provided via the --regexp parameter.

    Options:
      --strategy [not-matching|smaller|matching|newer|older]
                                      Removal strategy to apply on found
                                      duplicates.
      -r, --regexp REGEXP             Regular expression for file path. Required
                                      in matching and not-matching strategies.
      -n, --dry-run                   Do not actually remove anything; just show
                                      what would be removed.
      -s, --show-diffs                Show diffs between duplicates even if they
                                      are within the thresholds.
      -i, --message-id                Use Message-ID header as hash key. This is
                                      not recommended: the default is to compute a
                                      digest of the whole header with selected
                                      headers removed.
      -S, --size-threshold BYTES      Specify maximum allowed difference between
                                      size of duplicates. Set to -1 for no
                                      threshold.
      -D, --diff-threshold BYTES      Specify maximum allowed difference between
                                      size of duplicates. Set to -1 for no
                                      threshold.
      --help                          Show this message and exit.


Hashing command specific options:

.. code-block:: bash

    $ mdedup hash --help
    Usage: mdedup hash [OPTIONS] MESSAGE

      Take a single mail message and show its canonicalised form and hash.

      This is essentially provided for debugging why two messages do not have
      the same hash when you expect them to (or vice-versa).

      To get the message from STDIN, use a dash in place of the filename:
          cat mail.txt | mdedup hash -

    Options:
      -i, --message-id  Use Message-ID header as hash key. This is not
                        recommended: the default is to compute a digest of the
                        whole header with selected headers removed.
      --help            Show this message and exit.


Details
-------

This script reads all mails in a given list of maildir folders and subfolders,
then automatically detects, lists, and optionally deletes any duplicate mails.

Duplicate detection is done by cherry-picking certain headers, in some cases
doing some minor tweaking of the values to reduce them to a canonical form, and
then computing a digest of those headers concatenated together.

Note that we deliberately limit this to certain headers due to the effects that
mailing list software can have on not only the mail header but the body; it can
potentially:

* append a footer to a list body, thus changing the ``Content-Length`` header;

* create a new path described by the ``Received`` headers which would not be
  contained in any copy of the mail saved locally at the time it was sent to
  the list;

* munge the ``Reply-To`` header even though it's a bad idea;

* add plenty of other random headers which a copy saved locally at sending-time
  would not have, such as ``X-Mailman-Version``, ``Precedence``,
  ``X-BeenThere``, ``List-*``, ``Sender``, ``Errors-To``, and so on;

* add a prefix to the ``Subject`` header.

Another difficulty is the lack of guarantee that ``Message-ID`` is unique or
even present.  Yes, certain broken mail servers which must remain nameless are
guilty of this :-(

For added protection against accidentally removing mails due to false
positives, duplicates are verified by comparing body sizes and also diff'ing
the contents.  If the sizes or contents differ by more than a threshold, they
are not counted as duplicates.


Stability policy
----------------

Here is a bunch of rules we're trying to follow regarding stability:

* Patch releases (``0.x.n`` → ``0.x.(n+1)`` upgrades) are bug-fix only. These
  releases must not break anything and keeps backward-compatibility with
  ``0.x.*`` and ``0.(x-1).*`` series.

* Minor releases (``0.n.*`` → ``0.(n+1).0`` upgrades) includes any non-bugfix
  changes. These releases must be backward-compatible with any ``0.n.*``
  version but are allowed to drop compatibility with the ``0.(n-1).*`` series
  and below.

* Major releases (``n.*.*`` → ``(n+1).0.0`` upgrades) are not planned yet,
  unless we introduce huge changes to the project.


Contributors
------------

* `Kevin Deldycke <https://github.com/kdeldycke>`_
* `Adam Spiers <https://github.com/aspiers>`_
* `Ben Reser <https://github.com/breser>`_
* `Marcel Martin <https://github.com/marcelm>`_
* `reedog117 <https://github.com/reedog117>`_
* `Tristan Henderson <https://github.com/tnhh>`_
* `Matija Nalis <https://github.com/mnalis>`_
* `Painted-Fox <https://github.com/Painted-Fox>`_
* `Juan Diego Tascón <https://github.com/juantascon>`_
* `Kevin Murray <https://github.com/kdmurray91>`_


License
-------

This software is licensed under the `GNU General Public License v2 or later
(GPLv2+)
<https://github.com/kdeldycke/maildir-deduplicate/blob/master/LICENSE>`_.
