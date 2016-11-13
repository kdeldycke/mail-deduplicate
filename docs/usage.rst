Usage
=====

``mdedup``
----------

List global options and commands:

.. code-block:: shell-session

    $ mdedup --help
    Usage: mdedup [OPTIONS] COMMAND [ARGS]...

      CLI for maildirs content analysis and deletion.

    Options:
      -v, --verbosity LEVEL  Either CRITICAL, ERROR, WARNING, INFO or DEBUG
      --version              Show the version and exit.
      --help                 Show this message and exit.

    Commands:
      deduplicate  Deduplicate maildirs content.
      hash         Hash a single mail.


``mdedup deduplicate``
----------------------

Deduplication command specific options:

.. code-block:: shell-session

    $ mdedup deduplicate --help
    Usage: mdedup deduplicate [OPTIONS] [MAILDIRS]...

      Deduplicate mails from a set of maildir folders.

      Run a first pass computing the canonical hash of each encountered mail
      from their headers, then a second pass to apply the deletion strategy on
      each subset of duplicate mails.

      Removal strategies for each subsets of duplicate mails:
        - delete-older:    Deletes the olders,    keeps the newests.
        - delete-oldest:   Deletes the oldests,   keeps the newers.
        - delete-newer:    Deletes the newers,    keeps the oldests.
        - delete-newest:   Deletes the newests,   keeps the olders.
        - delete-smaller:  Deletes the smallers,  keeps the biggests.
        - delete-smallest: Deletes the smallests, keeps the biggers.
        - delete-bigger:   Deletes the biggers,   keeps the smallests.
        - delete-biggest:  Deletes the biggests,  keeps the smallers.
        - delete-matching-path: Deletes all duplicates whose file path match the
        regular expression provided via the --regexp parameter.
        - delete-non-matching-path: Deletes all duplicates whose file path
        doesn't match the regular expression provided via the --regexp parameter.

      Deletion strategy on a duplicate set only applies if no major differences
      between mails are uncovered during a fine-grained check differences during
      the second pass. Limits can be set via the threshold options.

    Options:
      -s, --strategy [delete-newest|delete-newer|delete-smallest|delete-matching-path|delete-non-matching-path|delete-oldest|delete-older|delete-smaller|delete-bigger|delete-biggest]
                                      Deletion strategy to apply within a subset
                                      of duplicates.
      -t, --time-source [date-header|ctime]
                                      Source of a mail's reference time. Required
                                      in time-sensitive strategies.
      -r, --regexp REGEXP             Regular expression against a mail file path.
                                      Required in delete-matching-path and delete-
                                      non-matching-path strategies.
      -n, --dry-run                   Do not actually delete anything; just show
                                      what would be removed.
      -i, --message-id                Only use the Message-ID header as a hash
                                      key. Not recommended. Replace the default
                                      behavior consisting in deriving the hash
                                      from several headers.
      -S, --size-threshold BYTES      Maximum allowed difference in size between
                                      mails. Whole subset of duplicates will be
                                      rejected above threshold. Set to -1 to not
                                      allow any difference. Defaults to 512 bytes.
      -C, --content-threshold BYTES   Maximum allowed difference in content
                                      between mails. Whole subset of duplicates
                                      will be rejected above threshold. Set to -1
                                      to not allow any difference. Defaults to 768
                                      bytes.
      -d, --show-diff                 Show the unified diff of duplicates not
                                      within thresholds.
      --help                          Show this message and exit.


``mdedup hash``
---------------

Hashing command specific options:

.. code-block:: shell-session

    $ mdedup hash --help
    Usage: mdedup hash [OPTIONS] MESSAGE

      Take a single mail message and show its canonicalised form and hash.

      Mainly used to debug message hashing.

    Options:
      -i, --message-id  Only use the Message-ID header as a hash key. Not
                        recommended. Replace the default behavior consisting in
                        deriving the hash from several headers.
      --help            Show this message and exit.
