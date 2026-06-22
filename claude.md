# CLAUDE.md

This file provides guidance to [Claude Code](https://claude.ai/code) when working with code in this repository.

## Project overview

Mail Deduplicate (`mdedup`) is a CLI that finds and removes duplicate mails across mail boxes. It reads `maildir`, `mbox`, `MH`, `Babyl` and `MMDF` boxes, groups mails into duplicate sets by a hash of selected headers, applies a user-chosen strategy to pick which copies to keep, then copies, moves or deletes the rest.

## Upstream conventions

This repository uses the reusable workflows and `pyproject.toml` configuration from [`kdeldycke/repomatic`](https://github.com/kdeldycke/repomatic) and follows the conventions established there. For code style, typing, documentation, testing and design principles, the upstream [`claude.md`](https://github.com/kdeldycke/repomatic/blob/main/claude.md) is the canonical reference. This file records only what is specific to mail-deduplicate.

**Contributing upstream:** if you spot a gap or improvement in the reusable workflows or shared conventions, propose it at [`kdeldycke/repomatic`](https://github.com/kdeldycke/repomatic/issues).

### Source of truth hierarchy

This file defines the rules; the codebase and CI are what those rules are measured against. When they disagree, fix the code to match. If a rule itself is wrong, fix this file.

### Keeping this file lean

Record only conventions, rationale and non-obvious rules that cannot be discovered by reading the code. Do not paste the module tree, source snippets or general Python knowledge here: reference the source instead.

## Commands

```shell-session
# Run the test suite (test dependencies live in the `test` group).
$ uv run --group test -- pytest

# Run a single test.
$ uv run --group test -- pytest tests/test_strategy.py::test_name

# Type-check with the CI-pinned mypy and minimum Python version.
$ uvx repomatic run mypy -- mail_deduplicate tests

# Build the documentation into the gitignored output directory.
$ uv run --group docs -- sphinx-build -b html ./docs ./docs/_build/html

# Run the CLI from the working tree.
$ uv run -- mdedup --help
```

## Architecture

`mdedup` runs a four-step pipeline, orchestrated by the `Deduplicate` class in `deduplicate.py`. Each step is documented in depth in `docs/design.md`:

1. **Load** the source boxes and read their mails (`mail_box.py`, `mail.py`).
2. **Hash** mails into `DuplicateSet`s keyed by a hash of selected headers (`deduplicate.py`).
3. **Select** which mails to keep within each set, via a selection strategy (`strategy.py`).
4. **Act** on the selected or discarded mails: copy, move or delete (`action.py`).

| Module           | Responsibility                                                                      |
| ---------------- | ----------------------------------------------------------------------------------- |
| `cli.py`         | The `mdedup` Click command, its `Config`, and option groups.                        |
| `deduplicate.py` | `Deduplicate` orchestrator, `DuplicateSet`, hashing, statistics (`Stats`).          |
| `mail.py`        | `DedupMailMixin`: a mail wrapped with dedup-relevant properties (hash, date, size). |
| `mail_box.py`    | Box formats (`BoxFormat`), autodetection, opening, locking, subfolders.             |
| `strategy.py`    | Selection strategies (oldest/newest, size, content, matching-path, ...).            |
| `action.py`      | Actions applied to the selected or discarded mails.                                 |

### Non-obvious rules

- `DedupMailMixin` is mixed into each `mailbox.Message` subclass at runtime by `make_dedup_mail()`, so every box format shares one dedup implementation. Keep format-specific code in `mail_box.py`; keep format-agnostic dedup logic on the mixin.
- Three opt-in safeguards make destructive runs safer: a minimal-headers floor, a size threshold and a content threshold. They are described in `docs/design.md`; run `mdedup --help` for the exact option names. When changing selection or hashing, re-read those safeguards: they exist to avoid deleting mails that only look like duplicates.
