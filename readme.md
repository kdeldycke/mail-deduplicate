<p align="center">
  <a href="https://github.com/kdeldycke/mail-deduplicate/">
    <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/images/mail-deduplicate-logo-header.png" alt="Mail Deduplicate">
  </a>
</p>

[![Last release](https://img.shields.io/pypi/v/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Python versions](https://img.shields.io/pypi/pyversions/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Unittests status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml?query=branch%3Amain)
[![Documentation status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml?query=branch%3Amain)
[![Coverage status](https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main/graph/badge.svg)](https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main)
[![DOI](https://zenodo.org/badge/9016537.svg)](https://zenodo.org/badge/latestdoi/9016537)

**What is Mail Deduplicate?**

Provides the `mdedup` CLI, an utility to deduplicate mails from a set of boxes.

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/images/cli-coloured-header.png" alt="Mail Deduplicate">
</p>

## Features

- Duplicate detection based on cherry-picked and normalized mail
  headers.
- Fetch mails from multiple sources.
- Reads and writes to `mbox`, `maildir`, `babyl`, `mh` and `mmdf`
  formats.
- Deduplication strategies based on size, content, timestamp, file path
  or random choice.
- Copy, move or delete the resulting set of duplicates.
- Dry-run mode.
- Protection against false-positives with safety checks on size and content differences.
- Supports macOS, Linux and Windows.
- Shell auto-completion for Bash, Zsh and Fish.

## Example

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/images/cli-coloured-run.png">
</p>

## Quickstart

Easiest way is to install `mdedup` with [`pipx`](https://pypa.github.io/pipx/):

```shell-session
$ pipx install mail-deduplicate
```

Other
[alternatives installation methods](https://kdeldycke.github.io/mail-deduplicate/install.html)
are available in the documentation.
