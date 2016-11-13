ChangeLog
=========


`2.0.0 (2016-11-13) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.3.0...v2.0.0>`_
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


`1.3.0 (2016-08-11) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.2.0...v1.3.0>`_
------------------------------------------------------------------------------------------------

* User-friendly progress bar.
* Decrease memory usage on large datasets. Closes #19, #8 and #3.
* Attempt several encodings when parsing message body. Closes #32.
* Fixed comparison issue in Python 3. Closes #34.
* Add a set of basic deduplication unittests.


`1.2.0 (2016-03-29) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.1.0...v1.2.0>`_
------------------------------------------------------------------------------------------------

* Use logger to output messages to the user.
* Activate tests on Python 3.3, PyPy and PyPy3.
* Fix date parsing. See #33.
* Fix decoding of unicode header value. Closes #24 and #32.


`1.1.0 (2016-01-10) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.0.2...v1.1.0>`_
------------------------------------------------------------------------------------------------

* Add Python 3.4 and 3.5 support. Closes #30.
* Add default ``isort`` configuration.
* Remove hackish default encoding forcing in main code.


`1.0.2 (2015-12-22) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.0.1...v1.0.2>`_
------------------------------------------------------------------------------------------------

* Fix ``AttributeError`` on message instance. Closes #28.
* Various fixes of references to internal variables introduced
  by a switch to more Pythonic classes in 1.0.0.
* Remove ``Message-ID`` from the list of default canonical headers.


`1.0.1 (2015-11-23) <https://github.com/kdeldycke/maildir-deduplicate/compare/v1.0.0...v1.0.1>`_
------------------------------------------------------------------------------------------------

* Switch from coveralls.io to codecov.io.


`1.0.0 (2015-10-03) <https://github.com/kdeldycke/maildir-deduplicate/compare/v0.1.0...v1.0.0>`_
------------------------------------------------------------------------------------------------

* Fix package version parsing.
* Add installation instructions. Closes #21.
* Add PEP8 and PyLint configuration.
* Add bumpversion configuration.
* Rework CLI around click framework. Closes #26.


`0.1.0 (2014-12-15) <https://github.com/kdeldycke/maildir-deduplicate/compare/v0.0.1...v0.1.0>`_
------------------------------------------------------------------------------------------------

* Package the script for proper distribution.


`0.0.1 (2011-04-27) <https://github.com/kdeldycke/maildir-deduplicate/compare/v0.0.0...v0.0.1>`_
------------------------------------------------------------------------------------------------

* First external contribution.


`0.0.0 (2010-06-08) <http://github.com/kdeldycke/maildir-deduplicate/compare/init...v0.0.0>`_
---------------------------------------------------------------------------------------------

* First commit.
