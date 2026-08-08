# Changelog

## [`9.3.1.dev0` (unreleased)](https://github.com/kdeldycke/mail-deduplicate/compare/v9.3.0...main)

> [!WARNING]
> This version is **not released yet** and is under active development.

## [`9.3.0` (2026-08-08)](https://github.com/kdeldycke/mail-deduplicate/compare/v9.2.0...v9.3.0)

- **Breaking:** a dry run now says `DRY RUN: N mails would be acted upon, but none will be altered.` once, in place of a `DRY RUN: Skip action.` line per mail. Scripts matching the old wording need updating.
- **Breaking:** Python importers must switch to `Strategy.function`/`Strategy.apply()`, `Action.perform()` and `DuplicateSet.select()`, which replace `strategy_function`/`apply_strategy()`, `perform_action()` and `categorize_candidates()`. The CLI is unchanged.
- Add a `hardlink-discarded` action: each discarded mail becomes a hardlink to the copy kept in its set, reclaiming its space while staying in its own folder. Only byte-identical copies are linked, unless `--hardlink-differing` is passed. Closes [#164](https://github.com/kdeldycke/mail-deduplicate/issues/164).
- Add `--cache` and `--cache-path`, off by default, to reuse the hashes of previous runs: a second run over a 20,000-mail maildir takes half the time. Entries expire with their mail or when the hashing options change. Closes [#87](https://github.com/kdeldycke/mail-deduplicate/issues/87).
- Spread hashing and selection over worker processes instead of threads, so `--jobs` finally pays off: a first run over a 20,000-mail maildir drops from `3.4s` to `1.8s` at `--jobs=4`. Only folder-based boxes (`maildir`, `MH`, `eml`) fan out.
- Speed up hashing by about `2x` and halve the file-system calls a `maildir` run makes per mail, taking a whole run about `2.6x` faster with the default `--hash-body skip`. Refs [#87](https://github.com/kdeldycke/mail-deduplicate/issues/87).
- Cut the memory retained per mail from about `950` to `600` bytes. Refs [#87](https://github.com/kdeldycke/mail-deduplicate/issues/87).
- Settle the size and content thresholds over the whole duplicate set instead of comparing every pair: a single set of 200 copies took `1.90s` and now takes `0.04s`.
- Cut what a run prints by seven eighths, from 32,000 lines to 4,000 on a 20,000-mail corpus: mails and duplicate sets are now named at `--verbosity DEBUG` only. The selection step gained a progress bar.
- Add `platformdirs` to the runtime dependencies, which resolves the per-platform location of the hash cache.
- Fix the documentation's broken links: `pipx`'s installation guide moved, and the `ctime` note now cites Python's `os.path.getctime` docs. Closes [#899](https://github.com/kdeldycke/mail-deduplicate/issues/899).
- Add a performance page covering where a run spends its time, the memory it holds and how to manage the hash cache, plus tutorial and design sections on hardlinking. Correct the per-mail memory figures, which claimed a few hundred bytes.

## [`9.2.0` (2026-08-07)](https://github.com/kdeldycke/mail-deduplicate/compare/v9.1.0...v9.2.0)

> [!NOTE]
> `9.2.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/9.2.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v9.2.0).

- Keep memory usage flat whatever the size of the mail sources: a 215 MB maildir of 1,500 mails peaks at 48 MB of resident memory instead of 283 MB. Closes [#761](https://github.com/kdeldycke/mail-deduplicate/issues/761), and removes the memory pressure motivating [#87](https://github.com/kdeldycke/mail-deduplicate/issues/87).
- Fix the threshold options' help, which still claimed a breach skips the whole duplicate set instead of setting the offending mails aside.
- Drop the non-existent content-based strategy from the README's feature list.

## [`9.1.0` (2026-08-01)](https://github.com/kdeldycke/mail-deduplicate/compare/v9.0.0...v9.1.0)

> [!NOTE]
> `9.1.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/9.1.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v9.1.0).

- **Breaking:** pluralize the repeatable options' parameter IDs: configuration keys and environment variables become `hash_headers`/`MDEDUP_HASH_HEADERS` and `strategies`/`MDEDUP_STRATEGIES`. The `--hash-header` and `--strategy` flags are unchanged.
- Skip duplicate sets containing mails with an unparsable or absent `Date` header instead of crashing on time-based strategies. The warning names the offending mails, and a new `Skipped - Timestamp` metric counts these sets. Closes [#132](https://github.com/kdeldycke/mail-deduplicate/issues/132) and [#600](https://github.com/kdeldycke/mail-deduplicate/issues/600).
- Identify mails from folder-based boxes in logs by the fully-qualified path of their own file, so it can be copy-pasted for direct inspection. Closes [#157](https://github.com/kdeldycke/mail-deduplicate/issues/157).
- Set aside mails exceeding the size or content thresholds against the rest of their set instead of skipping the whole set, so an outlier no longer prevents the deduplication of the true copies sharing its hash. Closes [#851](https://github.com/kdeldycke/mail-deduplicate/issues/851).
- Discover nested maildir folders stored as plain directories at any depth, as produced by `isync`/`mbsync`'s Verbatim naming style, even when the root directory holds no mail itself. Closes [#973](https://github.com/kdeldycke/mail-deduplicate/issues/973).
- Add a new `eml` source and export format, reading and writing loose `.eml` files from a folder, walked recursively. Autodetected, and the unrecognized-folder error now points at `--input-format`. Closes [#760](https://github.com/kdeldycke/mail-deduplicate/issues/760).
- Allow repeating `--strategy` to chain fallback strategies: each duplicate set is handed over to the next strategy when one fails to discriminate its mails. Closes [#647](https://github.com/kdeldycke/mail-deduplicate/issues/647).
- Report each copied, moved or deleted mail with a live `✓` trail line and a timed summary on interactive terminals.
- Validate the `--regexp` and `--export` option requirements at parse time with `cloup` constraints, rewording their error messages.
- Reject configuration files carrying keys that match no CLI option, and refuse mail sources from configuration files: boxes to deduplicate are always passed on the command line.
- Accept kebab-case keys in configuration files, matching the spelling of the CLI flags.
- Ship the TOML writer so `--export-config toml` works out of the box, and name every configurable option in generated templates, commented out when unset, under kebab-case keys.
- Stop requiring `--export` in `-H`/`--hash-only` mode: constraints from the selection and action steps no longer apply there.
- Drop `boltons` and `whenever` from the runtime dependencies (both remain for tests) and require `click-extra` `8.7`, whose `--params` and `--export-config` now reflect the loaded configuration file.
- Build the prebuilt Linux executables inside a `manylinux_2_28` container so they link against a glibc `2.28` floor instead of the CI runner's newer glibc, letting them run on older enterprise distributions such as RHEL 8+, Debian 10, Ubuntu 20.04 and openSUSE Leap 15.3+. Closes [#759](https://github.com/kdeldycke/mail-deduplicate/issues/759).
- Fix a spurious metrics-inconsistency exit (code `115`) for `*-discarded` actions and dry runs: the statistics self-check now compares each action counter to the subset of mails the action targets. Closes [#841](https://github.com/kdeldycke/mail-deduplicate/issues/841).
- Fix an unhandled traceback on invalid `--regexp` values, now rejected with a proper parameter error.
- Fix the payload memory purge of selected mails, which never triggered for the `move-discarded` action.
- Add a hands-on tutorial page to the documentation and rework the README quickstart around use cases and example commands. Closes [#984](https://github.com/kdeldycke/mail-deduplicate/issues/984).
- Execute the tutorial's commands at documentation build time with `click-extra`'s `click:run` directives, so the rendered outputs always match the current implementation. Closes [#23](https://github.com/kdeldycke/mail-deduplicate/issues/23).
- Rewrite the configuration documentation: precedence, key spelling, `pyproject.toml` discovery, template export, validation and environment variables.

## [`9.0.0` (2026-07-27)](https://github.com/kdeldycke/mail-deduplicate/compare/v8.1.2...v9.0.0)

> [!NOTE]
> `9.0.0` is available on [🐍 PyPI](https://pypi.org/project/mail-deduplicate/9.0.0/) and [🐙 GitHub](https://github.com/kdeldycke/mail-deduplicate/releases/tag/v9.0.0).

- **Breaking:** upgrade to `click-extra` `8.1`, which renames the `--show-params` option to `--params`. The upgrade also drops the removed `ExtraCommand` import that broke `8.1.2` against recent `click-extra`. Closes [#1009](https://github.com/kdeldycke/mail-deduplicate/issues/1009).
- **Breaking:** remove the `-m`/`--minimal-headers` option. The per-mail floor is now derived automatically as `min(4, number of --hash-header values)`, so narrowing the hash below four headers, down to a single one, no longer needs a separate flag. Closes [#974](https://github.com/kdeldycke/mail-deduplicate/issues/974).
- Fix `AttributeError` crash in `-H`/`--hash-only` mode when displaying each mail's canonical headers. Closes [#1004](https://github.com/kdeldycke/mail-deduplicate/issues/1004).
- Add `--jobs` option to parallelize mail hashing.
- Add `--theme` option to select the CLI color theme.
- Migrate repository tooling, CI and release automation to [`repomatic`](https://github.com/kdeldycke/repomatic) reusable workflows. Replace Dependabot with Renovate.
- Adopt the PEP 440 `.devN` development versioning scheme.
- Switch to the `uv_build` build backend and declare the license as an SPDX expression.
- Move `test`, `typing` and `docs` extras to dependency groups.
- Replace the `arrow` date library with [`whenever`](https://github.com/ariebovenberg/whenever).
- Rename the development documentation page to contributing, convert the API docs to MyST Markdown and add a Claude Code project guide.
- Render GitHub-style alerts in the documentation with the native `alert` extension of `myst-parser` `5.1`.
- Run the test suite in parallel with `pytest-xdist`, import test modules via `importlib` and restrict collection to `tests/`.
- Run the CLI test suite in every CI matrix cell and move package-install smoke tests to a dedicated CI job.
- Drop the Codecov Test Analytics upload and the `junit.xml` artifact it required.

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
