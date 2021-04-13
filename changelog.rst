ChangeLog
=========


`6.1.4 (unreleased) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.3...develop>`_
----------------------------------------------------------------------------------------------

.. note:: This version is not yet released and is under active development


`6.1.3 (2021-04-13) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.2...v6.1.3>`_
---------------------------------------------------------------------------------------------

* Fix dynamic ``mailbox.Message`` inheritance. Closes #191.


`6.1.2 (2021-01-26) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.1...v6.1.2>`_
---------------------------------------------------------------------------------------------

* Reconcile ``v3`` branch with ``develop``.


`6.1.1 (2021-01-26) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.0...v6.1.1>`_
---------------------------------------------------------------------------------------------

* Simple re-release.


`6.1.0 (2021-01-26) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.2...v6.1.0>`_
---------------------------------------------------------------------------------------------

* Add retroactive support for Python 3.6. Closes #154.
* Fix documentation link and generation. Closes #66.
* Auto-generate API documentation via a GitHub action workflow.
* Add ``tomlkit`` dependency.
* Add test runs against new OSes and distributions: ``ubuntu-18.04`` and
  ``macos-11.0``.
* Remove ``pycodestyle``, it brings nothing more now that we rely on ``black``.


`6.0.2 (2020-11-05) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.1...v6.0.2>`_
---------------------------------------------------------------------------------------------

* Load up all subfolders from ``Maildir`` and ``MH`` boxes. Closes #123.


`6.0.1 (2020-10-22) <https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.0...v6.0.1>`_
---------------------------------------------------------------------------------------------

* Check early that ``--export`` file doesn't exists. Closes #119.
* Add screenshots.


`6.0.0 (2020-10-17) <https://github.com/kdeldycke/mail-deduplicate/compare/v5.1.0...v6.0.0>`_
---------------------------------------------------------------------------------------------

* Add new ``-a``/``--action`` option to choose what to do on the final mail
  selection.
* Implements new ``copy-discarded``, ``copy-selected``, ``delete-discarded``,
  ``delete-selected``, ``move-discarded`` and ``move-selected`` actions.
* Add new ``-E``/``--export`` and ``-e``/``--export-format`` options to support
  the new ``copy-*`` and ``moved-*`` actions.
* Rename all ``--delete-*`` strategies to ``--discard-*``.
* Add ``--select-*`` aliases to all strategies.
* Add new ``discard-all-but-one``, ``discard-one``, ``select-one`` and
  ``select-all-but-one`` selection strategies.
* Rename ``-f``/``--sources-format`` option to ``-i``/``--input-format``.
* ``--time-source`` parameter is now optional and defaults to ``date-header``.
* Add metric description in deduplication end report.
* Add detailed strategy description in help screen's epilog.
* Colorize help screen.
* Colorize version screen and print environment data for bug reports.
* Run tests on Python 3.9.


`5.1.0 (2020-10-06) <https://github.com/kdeldycke/mail-deduplicate/compare/v5.0.0...v5.1.0>`_
---------------------------------------------------------------------------------------------

* Add new ``-h``/``--hash-header`` option to select which mail headers to use
  to compute hash.
* Remove ``-i``/``--message-id`` option. Can be emulated with ``-h
  Message-ID`` or ``--hash-header Message-ID`` option.
* Make all keyword-based choice parameters (``--sources-format``, ``--strategy`` and
  ``--time-source``) case-insensitive.


`5.0.0 (2020-10-05) <https://github.com/kdeldycke/mail-deduplicate/compare/v4.0.0...v5.0.0>`_
---------------------------------------------------------------------------------------------

* Add supports for ``Babyl``, ``MH`` and ``MMDF`` mailbox types.
* Add new ``-f``/``--sources-format`` option to force the type of mail sources
  on opening.
* Add new ``-u``/``--force-unlock`` option to force the removal of a lock on
  mailboxes on opening.
* Split-up the selection of mails candidate for removal and the deletion itself
  into two distinct batch operations.
* Add issue templates to guide users to report bugs and request features.
* Upgrade to ``Poetry 1.1.0``.
* Test publishing to PyPi in dry-run mode by the way of Poetry.
* Auto-optimize images.
* Auto-lock closed issues and PRs after a moment of inactivity.


`4.0.0 (2020-10-02) <https://github.com/kdeldycke/mail-deduplicate/compare/v3.0.0...v4.0.0>`_
---------------------------------------------------------------------------------------------

* Removes the ``hash`` subcommand. Replaced it with a ``--hash-only`` parameter
  to the main dedupe command.
* Removes ``deduplicate`` subcommand. ``mdedup`` is now a simple CLI.
* Fix calls to deduplication stategy. Closes #86 and #88.
* Fix computation of stats. Closes #89.
* Drop support for Python 2. Refs #90.
* Bump minimal Python requirement to 3.7.
* Repackage project around Poetry and ``pyproject.toml``. Get rid of
  ``setup.py``.
* Replace unmaintained ``bumpversion`` by ``bump2version``.
* Drop dependency on ``progressbar2`` and replace it with ``click``'s.
  Closes #37.
* Switch from Travis to GitHub Actions for all CI/CD jobs.
* Regularly run unittests against Windows, Linux and macOS.
* Removes all copyright dates.
* Auto-fix Python format, typos and JSON content.
* Let dependabot check for dependencies and update them.
* Keep ``.gitignore`` and ``.mailmap`` up to date and in sync.
* Auto-publish package on tagging events via ``twine``.
* Always run test build and check resulting package on each commits.
* Use declarative JSON to maintain list of GitHub labels for issues and PRs.
* Lint both Python code and YAML content on each commit.
* Run unittests in random to order to detect coupling.


`3.0.1 (2021-01-25) <https://github.com/kdeldycke/mail-deduplicate/compare/v3.0.0...v3.0.1>`_
---------------------------------------------------------------------------------------------

* Add explicit warning in CLI output to warn about 3.x branch deprecation.
  Refs #180.


`3.0.0 (2020-09-03) <https://github.com/kdeldycke/maildir-deduplicate/compare/v2.2.0...v3.0.0>`_
------------------------------------------------------------------------------------------------

.. DANGER::
   As of ``v3.0.0``, the project has been renamed to *Mail Deduplicate* and is
   now available on:

   * Github at https://github.com/kdeldycke/mail-deduplicate
   * PyPi at https://pypi.org/project/mail-deduplicate

* Rename project from ``maildir-deduplicate`` to ``mail-deduplicate``.
* Rename ``master`` branch to ``main``.
* Add support for mboxes. Closes #48.
* Remove requirement on ``-s``/``--strategy`` parameter, to let mails being
  grouped into duplicate sets without any removal action, effectively acting as
  a second-level dry-run.


`2.2.0 (2020-09-03) <https://github.com/kdeldycke/mail-deduplicate/compare/v2.1.0...v2.2.0>`_
---------------------------------------------------------------------------------------------

.. warning::
   This is the last version of the project known under the name *Maildir
   Deduplicate* (a.k.a. ``maildir-deduplicate``).

* Add disclaimer to prepare project name change.
* Fix Header being object instead of string (#61).
* Make body_lines conversion more reliable.
* Fix bugs in counter statistics (#45, #57).
* Add Message-ID as a header to check.
* Fix ``UnicodeDecodeError``. Closes #53 and #55.
* Bump requirement to ``click_log >= 0.2.0``. Closes #58, #59 and #60.
* Replace ``nose`` by ``pytest``.
* Only notify by mail of test failures.
* Drop support of Python 3.3.


`2.1.0 (2017-01-13) <https://github.com/kdeldycke/mail-deduplicate/compare/v2.0.1...v2.1.0>`_
------------------------------------------------------------------------------------------------

* Fix rendering of changelog link in RST.
* Show selected log level in debug mode.
* Test builds against Python 3.6 and 3.7-dev, and most recent PyPy targetting
  Python 2.7 and 3.3.
* Bump requirement to ``readme_renderer >= 16.0``.
* Skip sets with unparseable mails because of incorrect encoding. Closes #47,
  #41 and #39.
* Require the ``-s``/``--strategy`` CLI parameter to be set. Closes #44.


`2.0.1 (2016-11-28) <https://github.com/kdeldycke/mail-deduplicate/compare/v2.0.0...v2.0.1>`_
------------------------------------------------------------------------------------------------

* Reject mails without ``Message-ID`` headers if ``--message-id`` option is
  active.
* Add a class to holds global config.
* Print more debug info in unittests when CLI produce tracebacks.
* Always check for package metadata in Travis CI jobs.
* Fix package's long description against PyPi rendering constraints.
* Add link to full changelog in package's long description.


`2.0.0 (2016-11-13) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.3.0...v2.0.0>`_
------------------------------------------------------------------------------------------------

* Refactor and redefine all removal strategies. Closes #40.
* Add a new ``-t``/``--time-source`` CLI parameter to point to the canonical
  source of a mail's timestamp.
* Rename ``-s``/``--show-diffs`` parameter to ``-d``/``--show-diff``.
* Rename ``-D``/``--diff-threshold`` parameter to
  ``-C``/``--content-threshold``.
* Add new ``-s`` shorthand to ``--strategy`` parameter.
* Re-implement diff threshold options. Closes #43.
* Re-implement statistics. Closes #42.
* Normalize and canonicalize all paths to deduplicate on the fly mails pointing
  to the same file.
* Build documentation via Sphinx.
* Add ``test`` and ``develop`` dependencies.
* Move coverage config to ``setup.cfg``.
* Replace ``pep8`` package by ``pycodestyle``.
* Enforce ``pycodestyle`` checks in Travis CI jobs.
* Remove popularity badge: PyPI download counters are broken and no longer
  displayed.
* Test production of packages in Travis CI jobs.
* Move development and packaging documentation to Sphinx. Closes #22.
* Make wheels generated under Python 2 environnment available for Python 3 too.
* Let unittests generates their own fake and temporary maildirs.
* Print CLI output in unittests.
* Use generic factory to produce mail fixtures in unittests.
* Only show latest changes in the long description of the package instead of
  the full changelog.


`1.3.0 (2016-08-11) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.2.0...v1.3.0>`_
------------------------------------------------------------------------------------------------

* User-friendly progress bar.
* Decrease memory usage on large datasets. Closes #19, #8 and #3.
* Attempt several encodings when parsing message body. Closes #32.
* Fixed comparison issue in Python 3. Closes #34.
* Add a set of basic deduplication unittests.


`1.2.0 (2016-03-29) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.1.0...v1.2.0>`_
------------------------------------------------------------------------------------------------

* Use logger to output messages to the user.
* Activate tests on Python 3.3, PyPy and PyPy3.
* Fix date parsing. See #33.
* Fix decoding of unicode header value. Closes #24 and #32.


`1.1.0 (2016-01-10) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.2...v1.1.0>`_
------------------------------------------------------------------------------------------------

* Add Python 3.4 and 3.5 support. Closes #30.
* Add default ``isort`` configuration.
* Remove hackish default encoding forcing in main code.


`1.0.2 (2015-12-22) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.1...v1.0.2>`_
------------------------------------------------------------------------------------------------

* Fix ``AttributeError`` on message instance. Closes #28.
* Various fixes of references to internal variables introduced
  by a switch to more Pythonic classes in 1.0.0.
* Remove ``Message-ID`` from the list of default canonical headers.


`1.0.1 (2015-11-23) <https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.0...v1.0.1>`_
------------------------------------------------------------------------------------------------

* Switch from coveralls.io to codecov.io.


`1.0.0 (2015-10-03) <https://github.com/kdeldycke/mail-deduplicate/compare/v0.1.0...v1.0.0>`_
------------------------------------------------------------------------------------------------

* Fix package version parsing.
* Add installation instructions. Closes #21.
* Add PEP8 and PyLint configuration.
* Add bumpversion configuration.
* Rework CLI around click framework. Closes #26.


`0.1.0 (2014-12-15) <https://github.com/kdeldycke/mail-deduplicate/compare/v0.0.1...v0.1.0>`_
------------------------------------------------------------------------------------------------

* Package the script for proper distribution.


`0.0.1 (2011-04-27) <https://github.com/kdeldycke/mail-deduplicate/compare/v0.0.0...v0.0.1>`_
------------------------------------------------------------------------------------------------

* First external contribution.


`0.0.0 (2010-06-08) <https://github.com/kdeldycke/mail-deduplicate/compare/init...v0.0.0>`_
----------------------------------------------------------------------------------------------

* First commit.
