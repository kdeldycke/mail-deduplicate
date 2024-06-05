<p align="center">
  <a href="https://github.com/kdeldycke/mail-deduplicate/">
    <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/mail-deduplicate-logo-header.png" alt="Mail Deduplicate">
  </a>
</p>

[![Last release](https://img.shields.io/pypi/v/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Python versions](https://img.shields.io/pypi/pyversions/mail-deduplicate.svg)](https://pypi.python.org/pypi/mail-deduplicate)
[![Unittests status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml?query=branch%3Amain)
[![Documentation status](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml/badge.svg?branch=main)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml?query=branch%3Amain)
[![Coverage status](https://codecov.io/gh/kdeldycke/mail-deduplicate/branch/main/graph/badge.svg)](https://app.codecov.io/gh/kdeldycke/mail-deduplicate)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.7364256.svg)](https://doi.org/10.5281/zenodo.7364256)

**What is Mail Deduplicate?**

Provides the `mdedup` CLI, an utility to deduplicate mails from a set of boxes.

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/cli-coloured-header.png" alt="Mail Deduplicate">
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
- [Standalone executables](#executables) for Linux, macOS and Windows.
- Shell auto-completion for Bash, Zsh and Fish.

> ⚠️ **Warning**: Performances
>
> `mdedup` implementation is quite naive at the moment and everything resides in memory.
>
> If this is good enough for a volume of a couple of gigabytes, the more emails `mdedup` try to parse, the closer you'll reach the memory limits of your machine. In which case [`mdedup` will exit abrubtly](https://github.com/kdeldycke/mail-deduplicate/issues/362#issuecomment-1266743045), zapped by the [OOM killer](https://en.wikipedia.org/wiki/Out_of_memory) of your OS. Of course your mileage may vary depending on your hardware.
>
> You can influence implementation of this feature with pull requests, or [purchase of business support 🤝 and sponsorship 🫶](https://github.com/sponsors/kdeldycke).

## Example

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/cli-coloured-run.png">
</p>

## Installation

### From sources

Easiest way is to install `mdedup` from sources with [`pipx`](https://pipx.pypa.io):

```shell-session
$ pipx install mail-deduplicate
```

Other
[alternatives installation methods](https://kdeldycke.github.io/mail-deduplicate/install.html)
are available in the documentation.

### Executables

Standalone executables of `mdedup`'s latest version are available for several platforms and architectures:

| Platform    | `x86_64`                                                                                                                           |`arm64`                                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------- |-------------------------------------------------------------------------------------------------------------------------------- |
| **Linux**   | [Download `mdedup-linux-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-linux-x64.bin)     | |
| **macOS**   | [Download `mdedup-macos-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-x64.bin)     | [Download `mdedup-macos-arm64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-arm64.bin) |
| **Windows** | [Download `mdedup-windows-x64.exe`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-windows-x64.exe) | |