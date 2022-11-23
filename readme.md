# Mail Deduplicate

[![Last release](https://img.shields.io/pypi/v/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Python versions](https://img.shields.io/pypi/pyversions/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Unittests status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml?query=branch%3Amain)
[![Documentation status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml?query=branch%3Amain)
[![Coverage status](https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main/graph/badge.svg)](https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main)
[![DOI](https://zenodo.org/badge/XXXXXXXX.svg)](https://zenodo.org/badge/latestdoi/XXXXXXXX)


<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/cli-coloured-header.png" alt="Mail Deduplicate">
</p>

**What is Mail Deduplicate?**

Provides the `mdedup` CLI, an utility to deduplicate mails from a set of boxes.

## Features

- Duplicate detection based on cherry-picked and normalized mail
  headers.
- Source and deduplicate mails from multiple sources.
- Reads and writes to `mbox`, `maildir`, `babyl`, `mh` and `mmdf`
  formats.
- Multiple duplicate selection strategies based on size, content,
  timestamp, file path or random choice.
- Copy, move or delete the resulting set of mails after the
  deduplication.
- Dry-run mode.
- Protection against false-positives by checking for size and content
  differences.

## Example

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/cli-colored-help.png">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/cli-coloured-run.png">
</p>


## Quickstart

Easiest way is to install `mdedup` with [`pipx`](https://pypa.github.io/pipx/):

```shell-session
$ pipx install mail-deduplicate
```

Other
[alternatives installation methods](https://kdeldycke.github.io/mail-deduplicate/install.html)
are available in the documentation.