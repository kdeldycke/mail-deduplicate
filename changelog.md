# Changelog

## [`9.0.0.dev0` (unreleased)](https://github.com/kdeldycke/mail-deduplicate/compare/v8.1.2...main)

> [!WARNING]
> This version is **not released yet** and is under active development.

- Migrate repository tooling, CI and release automation to [`repomatic`](https://github.com/kdeldycke/repomatic) reusable workflows. Replace Dependabot with Renovate.
- Adopt the PEP 440 `.devN` development versioning scheme.
- Switch to the `uv_build` build backend and declare the license as an SPDX expression.

## [`8.1.2` (2025-12-02)](https://github.com/kdeldycke/mail-deduplicate/compare/v8.1.1...v8.1.2)

> [!NOTE]
> `8.1.2` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/8.1.2/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v8.1.2).

- Refactor some code to improve readability.

## [`8.1.1` (2025-12-01)](https://github.com/kdeldycke/mail-deduplicate/compare/v8.1.0...v8.1.1)

> [!NOTE]
> `8.1.1` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/8.1.1/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v8.1.1).

- Do not ignore duplicate sets with unique mails. Closes [#843](https://github.com/kdeldycke/mail-deduplicate/issues/843) and [#599](https://github.com/kdeldycke/mail-deduplicate/issues/599).
- Fix parsing of `Date` headers. Closes [#954](https://github.com/kdeldycke/mail-deduplicate/issues/954).

## [`8.1.0` (2025-11-27)](https://github.com/kdeldycke/mail-deduplicate/compare/v8.0.0...v8.1.0)

> [!NOTE]
> `8.1.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/8.1.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v8.1.0).

- Add new `-m`/`--minimal-headers` option to set the minimal number of headers required to compute a hash. Closes [#943](https://github.com/kdeldycke/mail-deduplicate/issues/943).
- Validate number of `--hash-header` options against `--minimal-headers` value.
- Require at least one header to be provided to the `--hash-header` option.
- Add installation instructions for `brew` on macOS and Arch Linux.
- Use mixin classes to share common code between mailbox types and avoid dynamic inheritance.

## [`8.0.0` (2025-11-21)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.6.2...v8.0.0)

> [!NOTE]
> `8.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/8.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v8.0.0).

- Log options explicitly set by user but ignored because of `--hash-only` mode.
- Add `--no-config`, `--table-format` options inherited from Click Extra.
- Table rendering in CLI output is now controlled by `--table-format` option.
- Remove direct dependency on `tabulate`, use `click-extra`'s table utilities instead.
- Add official support for Python 3.14.
- Remove maximum capped version of all dependencies (relax all `~=` specifiers to `>=`). This gives more freedom to downstream and upstream packagers. Document each minimal version choice.
- Move all typing-related imports behind a hard-coded `TYPE_CHECKING` guard to avoid runtime imports.
- Produce `mdedup-windows-arm64.exe` Windows binary for `arm64` architecture.
- Run tests on stable Python 3.14 release.
- Run tests on Python 3.15-dev, mark them as unstable.
- Skip tests on intermediate Python versions (`3.11`, `3.12` and `3.13`) to reduce CI load.
- Run tests on Python `3.14t` and `3.15t` free-threaded variants.
- Use `astral-sh/setup-uv` action to install `uv` instead of manually installing it with `pip`.
- Move `ubuntu-24.04` to `ubuntu-24.04-arm`, `macos-15` tests to `macos-26` and `windows-2025` tests to `windows-11-arm`.

## [`7.6.2` (2025-04-20)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.6.1...v7.6.2)

> [!NOTE]
> `7.6.2` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.6.2/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.6.2).

- Ignore line endings when comparing content. Closes [#844](https://github.com/kdeldycke/mail-deduplicate/issues/844).
- Render failed statistics assertions in plain English.
- Exit with error code `115` when statistics are inconsistent.
- Add a new `--verbose` option to increase the verbosity level.
- Reassign the short `-v` option from `--verbosity` to `--verbose`.
- Only run unittests against the oldest and newest major supported version of Python. Remove tests on `3.11` and `3.12`.
- To speed up the tests, we only test the latest available OS for each platform. Remove tests on `ubuntu-22.04`, `macos-13` and `windows-2019`.
- Upgrade tests from `windows-2022` to `windows-2025`.

## [`7.6.1` (2024-11-30)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.6.0...v7.6.1)

> [!NOTE]
> `7.6.1` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.6.1/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.6.1).

- Fix conflicting `-h`/`--hash-header` and `-h`/`--help` options. Closes [#762](https://github.com/kdeldycke/mail-deduplicate/issues/762).

## [`7.6.0` (2024-11-24)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.5.0...v7.6.0)

> [!NOTE]
> `7.6.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.6.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.6.0).

- Add official support for Python 3.13.
- Drop support for Python 3.9. Refs [#787](https://github.com/kdeldycke/mail-deduplicate/issues/787).
- Add dependency on `extra-platforms`. Closes [#784](https://github.com/kdeldycke/mail-deduplicate/issues/784).
- Run tests on stable Python 3.13 release.
- Run tests on Python 3.14-dev, mark them as unstable.
- Move `macos-14` tests to `macos-15`.
- Add tests on `ubuntu-24.04`. Remove tests on `ubuntu-20.04`.
- Run workflows on `ubuntu-24.04`.
- Rely on frozen `uv.lock` for reproducibility.

## [`7.5.0` (2024-07-03)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.4.0...v7.5.0)

> [!NOTE]
> `7.5.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.5.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.5.0).

- Switch from Poetry to `uv`.
- Drop support for Python 3.8.
- Mark Python 3.13-dev tests as stable.

## [`7.4.0` (2024-06-20)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.3.0...v7.4.0)

> [!NOTE]
> `7.4.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.4.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.4.0).

- Slim down package by moving unit tests out of the main package.
- Split `dev` dependency groups into optional `test`, `typing` and `docs` groups.
- Remove direct dependency on `mypy`.
- Run tests on Python `3.13-dev` on all platforms but `macos`.
- Run tests on `macos-14`. Drop tests on `macos-12`.
- Build `arm64` binaries on `macos-14`.

## [`7.3.0` (2023-11-15)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.2.3...v7.3.0)

> [!NOTE]
> `7.3.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.3.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.3.0).

- Drop support of Python 3.7.
- Reduce memory usage. Addresses [#362](https://github.com/kdeldycke/mail-deduplicate/issues/362).
- Replace unmaintained `bump2version` by `bump-my-version`.
- Test `mdedup` binaries.
- Run tests and actions on released Python 3.12 version.
- Run tests on macos-13. Remove tests on macos-11.

## [`7.2.3` (2023-05-04)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.2.2...v7.2.3)

> [!NOTE]
> `7.2.3` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.2.3/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.2.3).

- Reverts distribution of package via trusted channel.

## [`7.2.2` (2023-05-04)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.2.1...v7.2.2)

> [!NOTE]
> `7.2.2` is available on [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.2.2).

> [!WARNING]
> `7.2.2` is **not available** on 🐍 PyPI.

- Redo release to fix trusted publisher on PyPI.

## [`7.2.1` (2023-05-04)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.2.0...v7.2.1)

> [!NOTE]
> `7.2.1` is available on [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.2.1).

> [!WARNING]
> `7.2.1` is **not available** on 🐍 PyPI.

- Produce dependency graph in Mermaid instead of Graphviz. Add new dev dependency on `sphinxcontrib-mermaid`.
- Move all documentation assets to `assets` subfolder.
- Distribute package on PyPI via a trusted publisher channel.

## [`7.2.0` (2023-02-15)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.1.0...v7.2.0)

> [!NOTE]
> `7.2.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.2.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.2.0).

- Build standalone executable for macOS, Linux and Windows.
- Generates dependency graph in Graphviz format.
- Run tests on Python `3.12-dev`.
- Code, comments and documentation style change to conform to new QA workflows based on `ruff`.

## [`7.1.0` (2022-12-07)](https://github.com/kdeldycke/mail-deduplicate/compare/v7.0.0...v7.1.0)

> [!NOTE]
> `7.1.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.1.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.1.0).

- Renumber and rename phases to steps.
- Group options per steps.
- Add minimal code typing and checking.
- Add logo.
- Execute all workflows with Python 3.11.

## [`7.0.0` (2022-11-26)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.2.0...v7.0.0)

> [!NOTE]
> `7.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/7.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v7.0.0).

- Drop Python 3.6 support.
- Add support for Python 3.11.
- Add new `--time`/`--no-time` option to measure elapsed execution time.
- Add new `--color`/`--no-color` and `--ansi`/`--no-ansi` alias options to deactivate CLI color rendering.
- Add new `--color`/`--no-color` and `--ansi`/`--no-ansi` alias options to deactivate CLI color rendering.
- Add new `-C`/`--config` option which support local and remote configuration file in TOML, YAML, JSON, INI or XML formats.
- Add new `--show-params` option to debug default parameter value and provenance.
- Fix incconsistent printing of help screen. Closes [#160](https://github.com/kdeldycke/mail-deduplicate/issues/160).
- Force linear rendering of options in help screen to improve readability.
- Fix run on Python 3.10. Closes [#361](https://github.com/kdeldycke/mail-deduplicate/issues/361).
- Run unittests on Python 3.10 and Python 3.11.
- Add dependency on `click-extra` and `typing-extensions`
- Remove direct dependency on `click-help-colors`, `click-log` and `tomlkit`.
- Fix broken selection logic in quantity-based strategies. Refs [#146](https://github.com/kdeldycke/mail-deduplicate/issues/146).
- Add unittests to cover time-based and size-based selection edge-cases.
- Drop unittests on deprecated `ubuntu-18.04` and `macos-10.15`.
- Add unittests on `ubuntu-22.04`, `macos-12` and `windows-2022`.
- Run tests on multiple cores.
- Simplify project management by abandoning the dual use of `main`/`develop` branches.
- Migrate to external workflows to automate builds, releases, autofixes, linting, documentation, changelog, mailmap maintenance and label management.
- Convert all documentation from RST to Markdown. Closes [#368](https://github.com/kdeldycke/mail-deduplicate/issues/368).
- Keep CLI output in sync in documentation. Closes [#23](https://github.com/kdeldycke/mail-deduplicate/issues/23).
- Move `sphinx` dependencies to dev requirements.
- Add citation file.

## [`6.2.0` (2021-09-12)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.3...v6.2.0)

> [!NOTE]
> `6.2.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.2.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.2.0).

- Upgrade to Click 8.x.
- Implements all missing `copy-discarded`, `move-discarded` and
  `delete-discarded` actions. Closes [#270](https://github.com/kdeldycke/mail-deduplicate/issues/270) and [#146](https://github.com/kdeldycke/mail-deduplicate/issues/146).
- Add `-b`/`--hash-body` option to set the way each email body is
  hashed.
- Add `--export-append` option to allow for the resulting deduplicated
  email to be appended to an existing mail box.
- Skip duplicate sets without any matching duplicate candidates. Closes
  [#203](https://github.com/kdeldycke/mail-deduplicate/issues/203).

## [`6.1.3` (2021-04-14)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.2...v6.1.3)

> [!NOTE]
> `6.1.3` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.1.3/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.1.3).

- Fix dynamic `mailbox.Message` inheritance. Closes [#191](https://github.com/kdeldycke/mail-deduplicate/issues/191).

## [`6.1.2` (2021-01-26)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.1...v6.1.2)

> [!NOTE]
> `6.1.2` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.1.2/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.1.2).

- Reconcile `v3` branch with `develop`.

## [`6.1.1` (2021-01-26)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.1.0...v6.1.1)

> [!NOTE]
> `6.1.1` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.1.1/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.1.1).

- Simple re-release.

## [`6.1.0` (2021-01-26)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.2...v6.1.0)

> [!NOTE]
> `6.1.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.1.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.1.0).

- Add retroactive support for Python 3.6. Closes [#154](https://github.com/kdeldycke/mail-deduplicate/issues/154).
- Fix documentation link and generation. Closes [#66](https://github.com/kdeldycke/mail-deduplicate/issues/66).
- Auto-generate API documentation via a GitHub action workflow.
- Add `tomlkit` dependency.
- Add test runs against new OSes and distributions: `ubuntu-18.04` and
  `macos-11.0`.
- Remove `pycodestyle`, it brings nothing more now that we rely on
  `black`.

## [`6.0.2` (2020-11-05)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.1...v6.0.2)

> [!NOTE]
> `6.0.2` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.0.2/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.0.2).

- Load up all subfolders from `Maildir` and `MH` boxes. Closes [#123](https://github.com/kdeldycke/mail-deduplicate/issues/123).

## [`6.0.1` (2020-10-22)](https://github.com/kdeldycke/mail-deduplicate/compare/v6.0.0...v6.0.1)

> [!NOTE]
> `6.0.1` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.0.1/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.0.1).

- Check early that `--export` file doesn't exists. Closes [#119](https://github.com/kdeldycke/mail-deduplicate/issues/119).
- Add screenshots.

## [`6.0.0` (2020-10-17)](https://github.com/kdeldycke/mail-deduplicate/compare/v5.1.0...v6.0.0)

> [!NOTE]
> `6.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/6.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v6.0.0).

- Add new `-a`/`--action` option to choose what to do on the final mail
  selection.
- Implements new `copy-discarded`, `copy-selected`, `delete-discarded`,
  `delete-selected`, `move-discarded` and `move-selected` actions.
- Add new `-E`/`--export` and `-e`/`--export-format` options to support
  the new `copy-*` and `moved-*` actions.
- Rename all `--delete-*` strategies to `--discard-*`.
- Add `--select-*` aliases to all strategies.
- Add new `discard-all-but-one`, `discard-one`, `select-one` and
  `select-all-but-one` selection strategies.
- Rename `-f`/`--sources-format` option to `-i`/`--input-format`.
- `--time-source` parameter is now optional and defaults to
  `date-header`.
- Add metric description in deduplication end report.
- Add detailed strategy description in help screen's epilog.
- Colorize help screen.
- Colorize version screen and print environment data for bug reports.
- Run tests on Python 3.9.

## [`5.1.0` (2020-10-06)](https://github.com/kdeldycke/mail-deduplicate/compare/v5.0.0...v5.1.0)

> [!NOTE]
> `5.1.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/5.1.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v5.1.0).

- Add new `-h`/`--hash-header` option to select which mail headers to
  use to compute hash.
- Remove `-i`/`--message-id` option. Can be emulated with
  `-h Message-ID` or `--hash-header Message-ID` option.
- Make all keyword-based choice parameters (`--sources-format`,
  `--strategy` and `--time-source`) case-insensitive.

## [`5.0.0` (2020-10-05)](https://github.com/kdeldycke/mail-deduplicate/compare/v4.0.0...v5.0.0)

> [!NOTE]
> `5.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/5.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v5.0.0).

- Add supports for `Babyl`, `MH` and `MMDF` mailbox types.
- Add new `-f`/`--sources-format` option to force the type of mail
  sources on opening.
- Add new `-u`/`--force-unlock` option to force the removal of a lock on
  mailboxes on opening.
- Split-up the selection of mails candidate for removal and the deletion
  itself into two distinct batch operations.
- Add issue templates to guide users to report bugs and request
  features.
- Upgrade to `Poetry 1.1.0`.
- Test publishing to PyPI in dry-run mode by the way of Poetry.
- Auto-optimize images.
- Auto-lock closed issues and PRs after a moment of inactivity.

## [`4.0.0` (2020-10-02)](https://github.com/kdeldycke/mail-deduplicate/compare/v3.0.0...v4.0.0)

> [!NOTE]
> `4.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/4.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v4.0.0).

- Removes the `hash` subcommand. Replaced it with a `--hash-only`
  parameter to the main dedupe command.
- Removes `deduplicate` subcommand. `mdedup` is now a simple CLI.
- Fix calls to deduplication strategy. Closes [#86](https://github.com/kdeldycke/mail-deduplicate/issues/86) and [#88](https://github.com/kdeldycke/mail-deduplicate/issues/88).
- Fix computation of stats. Closes [#89](https://github.com/kdeldycke/mail-deduplicate/issues/89).
- Drop support for Python 2. Refs [#90](https://github.com/kdeldycke/mail-deduplicate/issues/90).
- Bump minimal Python requirement to 3.7.
- Repackage project around Poetry and `pyproject.toml`. Get rid of
  `setup.py`.
- Replace unmaintained `bumpversion` by `bump2version`.
- Drop dependency on `progressbar2` and replace it with `click`'s.
  Closes [#37](https://github.com/kdeldycke/mail-deduplicate/issues/37).
- Switch from Travis to GitHub Actions for all CI/CD jobs.
- Regularly run unittests against Windows, Linux and macOS.
- Removes all copyright dates.
- Auto-fix Python format, typos and JSON content.
- Let dependabot check for dependencies and update them.
- Keep `.gitignore` and `.mailmap` up to date and in sync.
- Auto-publish package on tagging events via `twine`.
- Always run test build and check resulting package on each commits.
- Use declarative JSON to maintain list of GitHub labels for issues and
  PRs.
- Lint both Python code and YAML content on each commit.
- Run unittests in random to order to detect coupling.

## [`3.0.1` (2021-01-25)](https://github.com/kdeldycke/mail-deduplicate/compare/v3.0.0...v3.0.1)

> [!NOTE]
> `3.0.1` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/3.0.1/).

> [!WARNING]
> `3.0.1` is **not available** on 🐙 GitHub.

- Add explicit warning in CLI output to warn about 3.x branch
  deprecation. Refs [#180](https://github.com/kdeldycke/mail-deduplicate/issues/180).

## [`3.0.0` (2020-09-03)](https://github.com/kdeldycke/mail-deduplicate/compare/v2.2.0...v3.0.0)

> [!CAUTION]
> As of `v3.0.0`, the project has been renamed to *Mail Deduplicate* and is
> now available on:
>
> - GitHub at https://github.com/kdeldycke/mail-deduplicate
> - PyPI at https://pypi.org/project/mail-deduplicate

> [!NOTE]
> `3.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/3.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v3.0.0).

- Rename project from `maildir-deduplicate` to `mail-deduplicate`.
- Rename `master` branch to `main`.
- Add support for mboxes. Closes [#48](https://github.com/kdeldycke/mail-deduplicate/issues/48).
- Remove requirement on `-s`/`--strategy` parameter, to let mails being
  grouped into duplicate sets without any removal action, effectively
  acting as a second-level dry-run.

## [`2.2.0` (2020-09-03)](https://github.com/kdeldycke/mail-deduplicate/compare/v2.1.0...v2.2.0)

> [!WARNING]
> This is the last version of the project known under the name *Maildir Deduplicate*
> (a.k.a. `maildir-deduplicate`).

> [!NOTE]
> `2.2.0` is the *first version* available on [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v2.2.0).

- Add disclaimer to prepare project name change.
- Fix Header being object instead of string (#61).
- Make body_lines conversion more reliable.
- Fix bugs in counter statistics ([#45](https://github.com/kdeldycke/mail-deduplicate/issues/45), [#57](https://github.com/kdeldycke/mail-deduplicate/issues/57)).
- Add Message-ID as a header to check.
- Fix `UnicodeDecodeError`. Closes [#53](https://github.com/kdeldycke/mail-deduplicate/issues/53) and [#55](https://github.com/kdeldycke/mail-deduplicate/issues/55).
- Bump requirement to `click_log >= 0.2.0`. Closes [#58](https://github.com/kdeldycke/mail-deduplicate/issues/58), [#59](https://github.com/kdeldycke/mail-deduplicate/issues/59) and [#60](https://github.com/kdeldycke/mail-deduplicate/issues/60).
- Replace `nose` by `pytest`.
- Only notify by mail of test failures.
- Drop support of Python 3.3.

## [`2.1.0` (2017-01-13)](https://github.com/kdeldycke/mail-deduplicate/compare/v2.0.1...v2.1.0)

- Fix rendering of changelog link in RST.
- Show selected log level in debug mode.
- Test builds against Python 3.6 and 3.7-dev, and most recent PyPy
  targeting Python 2.7 and 3.3.
- Bump requirement to `readme_renderer >= 16.0`.
- Skip sets with unparsable mails because of incorrect encoding. Closes
  [#47](https://github.com/kdeldycke/mail-deduplicate/issues/47), [#41](https://github.com/kdeldycke/mail-deduplicate/issues/41) and [#39](https://github.com/kdeldycke/mail-deduplicate/issues/39).
- Require the `-s`/`--strategy` CLI parameter to be set. Closes [#44](https://github.com/kdeldycke/mail-deduplicate/issues/44).

## [`2.0.1` (2016-11-28)](https://github.com/kdeldycke/mail-deduplicate/compare/v2.0.0...v2.0.1)

- Reject mails without `Message-ID` headers if `--message-id` option is
  active.
- Add a class to holds global config.
- Print more debug info in unittests when CLI produce tracebacks.
- Always check for package metadata in Travis CI jobs.
- Fix package's long description against PyPI rendering constraints.
- Add link to full changelog in package's long description.

## [`2.0.0` (2016-11-13)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.3.0...v2.0.0)

- Refactor and redefine all removal strategies. Closes [#40](https://github.com/kdeldycke/mail-deduplicate/issues/40).
- Add a new `-t`/`--time-source` CLI parameter to point to the canonical
  source of a mail's timestamp.
- Rename `-s`/`--show-diffs` parameter to `-d`/`--show-diff`.
- Rename `-D`/`--diff-threshold` parameter to
  `-C`/`--content-threshold`.
- Add new `-s` shorthand to `--strategy` parameter.
- Re-implement diff threshold options. Closes [#43](https://github.com/kdeldycke/mail-deduplicate/issues/43).
- Re-implement statistics. Closes [#42](https://github.com/kdeldycke/mail-deduplicate/issues/42).
- Normalize and canonicalize all paths to deduplicate on the fly mails
  pointing to the same file.
- Build documentation via Sphinx.
- Add `test` and `develop` dependencies.
- Move coverage config to `setup.cfg`.
- Replace `pep8` package by `pycodestyle`.
- Enforce `pycodestyle` checks in Travis CI jobs.
- Remove popularity badge: PyPI download counters are broken and no
  longer displayed.
- Test production of packages in Travis CI jobs.
- Move development and packaging documentation to Sphinx. Closes [#22](https://github.com/kdeldycke/mail-deduplicate/issues/22).
- Make wheels generated under Python 2 environnment available for Python
  3 too.
- Let unittests generates their own fake and temporary maildirs.
- Print CLI output in unittests.
- Use generic factory to produce mail fixtures in unittests.
- Only show latest changes in the long description of the package
  instead of the full changelog.

## [`1.3.0` (2016-08-11)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.2.0...v1.3.0)

- User-friendly progress bar.
- Decrease memory usage on large datasets. Closes [#19](https://github.com/kdeldycke/mail-deduplicate/issues/19), [#8](https://github.com/kdeldycke/mail-deduplicate/issues/8) and [#3](https://github.com/kdeldycke/mail-deduplicate/issues/3).
- Attempt several encodings when parsing message body. Closes [#32](https://github.com/kdeldycke/mail-deduplicate/issues/32).
- Fixed comparison issue in Python 3. Closes [#34](https://github.com/kdeldycke/mail-deduplicate/issues/34).
- Add a set of basic deduplication unittests.

## [`1.2.0` (2016-03-29)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.1.0...v1.2.0)

- Use logger to output messages to the user.
- Activate tests on Python 3.3, PyPy and PyPy3.
- Fix date parsing. See [#33](https://github.com/kdeldycke/mail-deduplicate/issues/33).
- Fix decoding of unicode header value. Closes [#24](https://github.com/kdeldycke/mail-deduplicate/issues/24) and [#32](https://github.com/kdeldycke/mail-deduplicate/issues/32).

## [`1.1.0` (2016-01-10)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.2...v1.1.0)

- Add Python 3.4 and 3.5 support. Closes [#30](https://github.com/kdeldycke/mail-deduplicate/issues/30).
- Add default `isort` configuration.
- Remove hackish default encoding forcing in main code.

## [`1.0.2` (2015-12-22)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.1...v1.0.2)

- Fix `AttributeError` on message instance. Closes [#28](https://github.com/kdeldycke/mail-deduplicate/issues/28).
- Various fixes of references to internal variables introduced by a
  switch to more Pythonic classes in 1.0.0.
- Remove `Message-ID` from the list of default canonical headers.

## [`1.0.1` (2015-11-23)](https://github.com/kdeldycke/mail-deduplicate/compare/v1.0.0...v1.0.1)

- Switch from coveralls to codecov.

## [`1.0.0` (2015-10-03)](https://github.com/kdeldycke/mail-deduplicate/compare/v0.1.0...v1.0.0)

- Fix package version parsing.
- Add installation instructions. Closes [#21](https://github.com/kdeldycke/mail-deduplicate/issues/21).
- Add PEP8 and PyLint configuration.
- Add bumpversion configuration.
- Rework CLI around click framework. Closes [#26](https://github.com/kdeldycke/mail-deduplicate/issues/26).

## [`0.1.0` (2014-12-15)](https://github.com/kdeldycke/mail-deduplicate/compare/v0.0.1...v0.1.0)

- Package the script for proper distribution.

## [`0.0.1` (2011-04-27)](https://github.com/kdeldycke/mail-deduplicate/compare/v0.0.0...v0.0.1)

- First external contribution.

## [`0.0.0` (2010-06-08)](https://github.com/kdeldycke/mail-deduplicate/compare/init...v0.0.0)

- First commit.
