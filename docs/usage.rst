Usage
=====

``mdedup``
----------

List global options and commands:

.. code-block:: bash

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


``mdedup deduplicate``
----------------------

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


``mdedup hash``
---------------

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
