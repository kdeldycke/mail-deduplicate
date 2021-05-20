Usage
=====

``mdedup``
----------

List global options:

.. code-block:: shell-session

    Usage: mdedup [OPTIONS] MAIL_SOURCE_1 MAIL_SOURCE_2 ...

      Deduplicate mails from a set of mail boxes.

      Process:
      * Phase #1: run a first pass to compute from their headers the canonical hash of
                  each encountered mail.
      * Phase #2: a second pass to apply the selection strategy on each subset of
                  duplicate mails sharing the same hash.
      * Phase #3: perform an action on all selected mails.

      A dozen of strategies are available to select mails in each subset:

      Time-based:
      * discard-older:    Discards the older,     keeps the newest.
      * discard-oldest:   Discards the oldest,    keeps the newer.
      * discard-newer:    Discards the newer,     keeps the oldest.
      * discard-newest:   Discards the newest,    keeps the older.

      Size-based:
      * discard-smaller:  Discards the smaller,  keeps the biggest.
      * discard-smallest: Discards the smallest, keeps the bigger.
      * discard-bigger:   Discards the bigger,   keeps the smallest.
      * discard-biggest:  Discards the biggest,  keeps the smaller.

      File-based:
      * discard-matching-path: Discards all duplicates whose file path match the
      regular expression provided via the --regexp parameter.
      * discard-non-matching-path: Discards all duplicates whose file path
      doesn't match the regular expression provided via the --regexp parameter.

      Action on the selected mails in phase #3 is only performed if no major
      differences between mails are uncovered during a fine-grained check
      differences in the second phase. Limits can be set via the --size-
      threshold and --content-threshold options.

    Options:
      -n, --dry-run                   Do not actually performs anything; just
                                      apply the selection strategy, and show which
                                      action would have been performed otherwise.

      -i, --input-format [babyl|maildir|mbox|mh|mmdf]
                                      Force all provided mail sources to be parsed
                                      in the specified format. If not set, auto-
                                      detect the format of sources independently.
                                      Auto-detection only supports maildir and
                                      mbox format. So use this option to open up
                                      other box format, or bypass unreliable
                                      detection.

      -u, --force-unlock              Remove the lock on mail source opening if
                                      one is found.

      -H, --hash-only                 Compute and display the internal hashes used
                                      to identify duplicates. Do not performs any
                                      deduplication operation.

      -h, --hash-header Header-ID     Headers to use to compute each mail's hash.
                                      Must be repeated multiple times to set an
                                      ordered list of headers. Header IDs are
                                      case-insensitive. Repeating entries are
                                      ignored. Defaults to: -h Date -h From -h To
                                      -h Subject -h MIME-Version -h Content-Type
                                      -h Content-Disposition -h User-Agent -h
                                      X-Priority -h Message-ID.

      -S, --size-threshold BYTES      Maximum difference allowed in size between
                                      mails sharing the same hash. The whole
                                      subset of duplicates will be rejected if at
                                      least one pair of mail exceed the threshold.
                                      Set to 0 to enforce strictness and
                                      deduplicate the subset only if all mails are
                                      exactly the same. Set to -1 to allow any
                                      difference and keep deduplicating the subset
                                      whatever the differences. Defaults to 512
                                      bytes.

      -C, --content-threshold BYTES   Maximum difference allowed in content
                                      between mails sharing the same hash. The
                                      whole subset of duplicates will be rejected
                                      if at least one pair of mail exceed the
                                      threshold. Set to 0 to enforce strictness
                                      and deduplicate the subset only if all mails
                                      are exactly the same. Set to -1 to allow any
                                      difference and keep deduplicating the subset
                                      whatever the differences. Defaults to 768
                                      bytes.

      -d, --show-diff                 Show the unified diff of duplicates not
                                      within thresholds.

      -s, --strategy [discard-bigger|discard-biggest|discard-matching-path|discard-newer|discard-newest|discard-non-matching-path|discard-older|discard-oldest|discard-smaller|discard-smallest]
                                      Selection strategy to apply within a subset
                                      of duplicates. If not set, duplicates will
                                      be grouped and counted but no selection will
                                      happen, and no action will be performed on
                                      the set.

      -t, --time-source [ctime|date-header]
                                      Source of a mail's time reference used in
                                      time-sensitive strategies. Defaults to date-
                                      header.

      -r, --regexp REGEXP             Regular expression against a mail file path.
                                      Required in discard-matching-path and
                                      discard-non-matching-path strategies.

      -v, --verbosity LEVEL           Either CRITICAL, ERROR, WARNING, INFO or
                                      DEBUG. Defaults to INFO.

      --version                       Show the version and exit.
      --help                          Show this message and exit.
