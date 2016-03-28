ChangeLog
=========


1.2.0 (2016-03-29)
------------------

* Use logger to output messages to the user.
* Activate tests on Python 3.3, PyPy and PyPy3.
* Fix date parsing. See #33.
* Fix decoding of unicode header value. Closes #24 and #32.


1.1.0 (2016-01-10)
------------------

* Add Python 3.4 and 3.5 support. Closes #30.
* Add default ``isort`` configuration.
* Remove hackish default encoding forcing in main code.


1.0.2 (2015-12-22)
------------------

* Fix ``AttributeError`` on message instance. Closes #28.
* Various fixes of references to internal variables introduced
  by a switch to more Pythonic classes in 1.0.0.
* Remove ``Message-ID`` from the list of default canonical headers.


1.0.1 (2015-11-23)
------------------

* Switch from coveralls.io to codecov.io.


1.0.0 (2015-10-03)
------------------

* Fix package version parsing.
* Add installation instructions. Closes #21.
* Add PEP8 and PyLint configuration.
* Add bumpversion configuration.
* Rework CLI around click framework. Closes #26.


0.1.0 (2014-12-15)
------------------

* Package the script for proper distribution.


0.0.1 (2011-04-27)
------------------

* First external contribution.


0.0.0 (2010-06-08)
------------------

* First commit.
