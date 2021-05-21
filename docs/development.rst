Development
===========


Philosophy
----------

1. First create something that works (to provide business value).
2. Then something that's beautiful (to lower maintenance costs).
3. Finally works on performance (to avoid wasting time on premature
   optimizations).


Stability policy
----------------

This project follows `Semantic Versioning <https://semver.org/>`_.

Which boils down to the following rules of thumb regarding stability:

* **Patch releases** (``0.x.n`` → ``0.x.(n+1)`` upgrades) are bug-fix only.
  These releases must not break anything and keep backward-compatibility with
  ``0.x.*`` and ``0.(x-1).*`` series.

* **Minor releases** (``0.n.*`` → ``0.(n+1).0`` upgrades) includes any
  non-bugfix changes. These releases must be backward-compatible with any
  ``0.n.*`` version but are allowed to drop compatibility with the
  ``0.(n-1).*`` series and below.

* **Major releases** (``n.*.*`` → ``(n+1).0.0`` upgrades) make no promises about
  backwards-compability.  Any API change requires a new major release.


Build status
------------

==============  ==================  ===================
Branch          |main-branch|__     |develop-branch|__
==============  ==================  ===================
Unittests       |build-stable|      |build-dev|
Coverage        |coverage-stable|   |coverage-dev|
Documentation   |docs-stable|       |docs-dev|
==============  ==================  ===================

.. |main-branch| replace::
   ``main``
__ https://github.com/kdeldycke/mail-deduplicate/tree/main
.. |develop-branch| replace::
   ``develop``
__ https://github.com/kdeldycke/mail-deduplicate/tree/develop

.. |build-stable| image:: https://github.com/kdeldycke/mail-deduplicate/workflows/Tests/badge.svg?branch=main
    :target: https://github.com/kdeldycke/mail-deduplicate/actions?query=workflow%3ATests+branch%3Amain
    :alt: Unittests status
.. |build-dev| image:: https://github.com/kdeldycke/mail-deduplicate/workflows/Tests/badge.svg?branch=develop
    :target: https://github.com/kdeldycke/mail-deduplicate/actions?query=workflow%3ATests+branch%3Adevelop
    :alt: Unittests status

.. |coverage-stable| image:: https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main/graph/badge.svg
    :target: https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main
    :alt: Coverage Status
.. |coverage-dev| image:: https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/develop/graph/badge.svg
    :target: https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/develop
    :alt: Coverage Status

.. |docs-stable| image:: https://readthedocs.org/projects/mail-deduplicate/badge/?version=stable
    :target: https://mail-deduplicate.readthedocs.io/en/stable/
    :alt: Documentation Status
.. |docs-dev| image:: https://readthedocs.org/projects/mail-deduplicate/badge/?version=develop
    :target: https://mail-deduplicate.readthedocs.io/en/develop/
    :alt: Documentation Status


Setup a development environment
-------------------------------

This **step is required** for all the other sections from this page.

Check out latest development branch:

.. code-block:: shell-session

    $ git clone git@github.com:kdeldycke/mail-deduplicate.git
    $ cd ./mail-deduplicate
    $ git checkout develop

Install package in editable mode with all development dependencies:

.. code-block:: shell-session

    $ pip install poetry
    $ poetry install

Now you're ready to hack and abuse git!


Unit-tests
----------

Install test dependencies and run unit-tests:

.. code-block:: shell-session

    $ poetry run pytest


Coding style
------------

Run `black <https://github.com/psf/black>`_ to auto-format Python code:

.. code-block:: shell-session

    $ poetry run black .

Then run `Pylint <https://docs.pylint.org>`_ code style checks:

.. code-block:: shell-session

    $ poetry run pylint mail_deduplicate


Documentation
-------------

The documentation you're currently reading can be built locally with `Sphinx
<https://www.sphinx-doc.org>`_:

.. code-block:: shell-session

    $ poetry install --extras docs
    $ poetry run sphinx-build -b html ./docs ./docs/html

The API documention is auto-generated from the code itself, and is taken care of
automatically by a `GitHub action workflow
<https://github.com/kdeldycke/mail-deduplicate/blob/develop/.github/workflows/autofix.yaml>`_.


Screenshots
-----------

Once in a while, the maintainers of the project will refresh screenshots found
in the documentation and the ``readme.rst`` file at the root of project.

To produce clean and fancy terminals screenshots, use either:

* https://graphite-shot.now.sh
* https://github.com/carbon-app/carbon
* https://codekeep.io/screenshot


Changelog
---------

From time to time, especially before a release, the maintainers will review and
rewrite the changelog to make it clean and readable. The idea is to have it
stay in the spirit of the `keep a changelog manifesto <https://keepachangelog.com>`_.

Most (if not all) changes can be derived by simply comparing the last tagged
release with the `develop` branch:
``https://github.com/kdeldycke/mail-deduplicate/compare/vX.X.X...develop``.
This direct link should be available at the top of the `changelog <changelog.html>`__ .


Release process
---------------

Check you are starting from a clean ``develop`` branch:

.. code-block:: shell-session

    $ git checkout develop

Revision should already be set to the next version, so we just need to set the
released date in the changelog:

.. code-block:: shell-session

    $ vi ./changelog.rst

Create a release commit, tag it and merge it back to ``main`` branch:

.. code-block:: shell-session

    $ git add ./mail_deduplicate/__init__.py ./changelog.rst
    $ git commit -m "Release vX.Y.Z"
    $ git tag "vX.Y.Z"
    $ git push
    $ git push --tags
    $ git checkout main
    $ git pull
    $ git merge "vX.Y.Z"
    $ git push

The next phases of the release process are automated and should be picked up by
GitHub actions. If not, the next section details the manual deployment process.


Manual build and deployment
---------------------------

Build packages:

.. code-block:: shell-session

    $ poetry build

For a smooth release, you also need to `validate the rendering of package's
long description on PyPi
<https://packaging.python.org/guides/making-a-pypi-friendly-readme/#validating-restructuredtext-markup>`_,
as well as metadata:

.. code-block:: shell-session

    $ poetry check
    $ poetry run twine check ./dist/*

Publish packaging to `PyPi <https://pypi.python.org>`_:

.. code-block:: shell-session

    $ poetry publish

Update revision with `bump2version <https://github.com/c4urself/bump2version>`_
and set it back to development state by increasing the ``patch`` level.

.. code-block:: shell-session

    $ git checkout develop
    $ poetry run bumpversion --verbose patch
    $ git add ./mail_deduplicate/__init__.py ./changelog.rst
    $ git commit -m "Post release version bump."
    $ git push


Version bump
------------

Versions are automatically bumped to their next ``patch`` revision at release
(see above). In the middle of your development, if the upcoming release is no
longer bug-fix only, or gets really important, feel free to bump to the next
``minor`` or ``major``:

.. code-block:: shell-session

    $ poetry run bumpversion --verbose minor
    $ git add ./mail_deduplicate/__init__.py ./changelog.rst
    $ git commit -m "Next release no longer bug-fix only. Bump revision."
    $ git push
