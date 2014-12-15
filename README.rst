Maildir Deduplicate
===================

Command-line tool to deduplicate mails from a set of maildir folders.

.. image:: https://badge.fury.io/py/maildir-deduplicate.svg
    :target: http://badge.fury.io/py/maildir-deduplicate
    :alt: Last release
.. image:: https://travis-ci.org/kdeldycke/maildir-deduplicate.svg?branch=develop
    :target: https://travis-ci.org/kdeldycke/maildir-deduplicate
    :alt: Unit-tests status
.. image:: https://img.shields.io/coveralls/kdeldycke/maildir-deduplicate.svg
    :target: https://coveralls.io/r/kdeldycke/maildir-deduplicate?branch=develop
    :alt: Coverage Status
.. image:: https://requires.io/github/kdeldycke/maildir-deduplicate/requirements.svg?branch=master
    :target: https://requires.io/github/kdeldycke/maildir-deduplicate/requirements/?branch=master
    :alt: Requirements freshness
.. image:: https://img.shields.io/pypi/l/maildir-deduplicate.svg
    :target: https://www.gnu.org/licenses/gpl-2.0.html
    :alt: Software license
.. image:: https://img.shields.io/pypi/dm/maildir-deduplicate.svg
    :target: https://pypi.python.org/pypi/maildir-deduplicate#downloads
    :alt: Popularity


Usage
-----

.. code-block::

    Usage: __init__.py [OPTIONS] [MAILDIR [MAILDIR ...]]

    Detect/remove duplicates from maildir folders

    Options:
      -h, --help            show this help message and exit
      -d, --remove-smaller  Remove all but largest duplicate in each duplicate set
      -r REGEXP, --remove-matching=REGEXP
                            Remove duplicates whose file path matches REGEXP
      -R REGEXP, --remove-not-matching=REGEXP
                            Remove duplicates whose file path does not match
                            REGEXP
      -o, --remove-older    Remove all but the newest duplicate (determined by
                        ctime) in each duplicate set
      -O, --remove-newer    Remove all but the oldest duplicate (determined by
                            ctime) in each duplicate set
      -n, --dry-run         Don't actually remove anything; just show what would
                            be removed.
      -s, --show-diffs      Show diffs between duplicates even if they're within
                            the thresholds
      -i, --message-id      Use Message-ID header as hash key (not recommended -
                            the default is to compute a digest of the whole header
                            with selected headers removed)
      -S BYTES, --size-threshold=BYTES
                            Specify maximum allowed difference between size of
                            duplicates. Default is 512; set -1 for no threshold.
      -D BYTES, --diff-threshold=BYTES
                            Specify maximum allowed size of unified diff between
                            duplicates. Default is 768; set -1 for no threshold.
      -H, --hash-pipe       Take a single mail message texted piped from STDIN and
                            show its canonicalised form and hash thereof. This is
                            useful for debugging why two messages don't have the
                            same hash when you expect them to (or vice-versa).


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

So far, it was tested on:

* MacOS X 10.6 with Python 2.6.2,
* Linux with Python 2.6.0 and 2.7.2.


Release process
---------------

.. code-block:: bash

    python setup.py register -r testpypi
    pip install wheel
    python setup.py sdist bdist_egg bdist_wheel upload -r testpypi
    git push --tags
    python setup.py register -r pypi
    python setup.py sdist bdist_egg bdist_wheel upload -r pypi


Contributors
------------

* `Kevin Deldycke <https://github.com/kdeldycke>`_
* `Adam Spiers <https://github.com/aspiers>`_
* `Ben Reser <https://github.com/breser>`_
* `Marcel Martin <https://github.com/marcelm>`_
* `reedog117 <https://github.com/reedog117>`_
* `Tristan Henderson <https://github.com/tnhh>`_
* `Matija Nalis <https://github.com/mnalis>`_


History
-------

This script was `initially released in 2010
<http://kevin.deldycke.com/2010/08/maildir-deduplication-script-python/>`_, and
was living in a `messy GitHub repository
<https://github.com/kdeldycke/scripts>`_. After some years, the script
basically outgrew its initial intent, and `moved in 2013 to its own repository
<http://kevin.deldycke.com/2013/06/maildir-deduplicate-moved/>`_.


License
-------

This software is licensed under the `GNU General Public License v2 or later
(GPLv2+)
<https://github.com/kdeldycke/maildir-deduplicate/blob/master/LICENSE>`_.
