<p align="center">
  <a href="https://github.com/kdeldycke/mail-deduplicate/">
    <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/mail-deduplicate-logo-header.png" alt="Mail Deduplicate">
  </a>
</p>

[![Last release](https://img.shields.io/pypi/v/mail-deduplicate.svg)](https://pypi.org/project/mail-deduplicate)
[![Python versions](https://img.shields.io/pypi/pyversions/mail-deduplicate.svg)](https://pypi.org/project/mail-deduplicate)
[![Downloads](https://static.pepy.tech/badge/mail-deduplicate/month)](https://pepy.tech/projects/mail-deduplicate)
[![Unittests status](https://img.shields.io/github/actions/workflow/status/kdeldycke/mail-deduplicate/tests.yaml?branch=main&label=%F0%9F%94%AC%20Tests)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/tests.yaml?query=branch%3Amain)
[![Coverage status](https://codecov.io/gh/kdeldycke/mail-deduplicate/graph/badge.svg?token=81NWQAPjEQ)](https://app.codecov.io/gh/kdeldycke/mail-deduplicate)
[![Documentation status](https://img.shields.io/github/actions/workflow/status/kdeldycke/mail-deduplicate/docs.yaml?branch=main&label=%F0%9F%93%9A%20Docs)](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/docs.yaml?query=branch%3Amain)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.7364256.svg)](https://doi.org/10.5281/zenodo.7364256)

**What is Mail Deduplicate?**

Provides the `mdedup` CLI, an utility to deduplicate mails from a set of boxes.

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/cli-coloured-header.png" alt="Mail Deduplicate">
</p>

## Features

- Duplicate detection based on cherry-picked and normalized mail headers.
- Fetch mails from multiple sources.
- Reads and writes to `mbox`, `maildir`, `babyl`, `mh` and `mmdf` formats.
- Deduplication strategies based on size, content, timestamp, file path or random choice.
- Copy, move or delete the resulting set of duplicates.
- Dry-run mode.
- Protection against false-positives with safety checks on size and content differences.
- Supports macOS, Linux and Windows.
- [Standalone executables](#executables) for Linux, macOS and Windows.
- Shell auto-completion for Bash, Zsh and Fish.

## Installation

All [installation methods](https://kdeldycke.github.io/mail-deduplicate/install.html) are available in the documentation. Below are the most popular ones:

### Try it now

[`uv`](https://docs.astral.sh/uv/getting-started/installation/) is the fastest way to run `mdedup` on any platform, thanks to its [`uvx` command](https://docs.astral.sh/uv/guides/tools/#running-tools):

```shell-session
$ uvx --from mail-deduplicate -- mdedup
```

### macOS

`mdedup` is part of the official [Homebrew](https://brew.sh) default tap, so you can install it with:

```shell-session
$ brew install mail-deduplicate
```

### Executables

Standalone binaries of `mdedup`'s latest version are available as direct downloads for several platforms and architectures:

| Platform    | `arm64`                                                                                                                                | `x86_64`                                                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **Linux**   | [Download `mdedup-linux-arm64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-linux-arm64.bin)     | [Download `mdedup-linux-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-linux-x64.bin)     |
| **macOS**   | [Download `mdedup-macos-arm64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-arm64.bin)     | [Download `mdedup-macos-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-x64.bin)     |
| **Windows** | [Download `mdedup-windows-arm64.exe`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-windows-arm64.exe) | [Download `mdedup-windows-x64.exe`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-windows-x64.exe) |

## Quickstart

Duplicate mails pile up whenever boxes get copied around: backups of the same account taken at different times, per-folder exports where a mail tagged with several labels lands in several boxes, archives consolidated from multiple clients, or IMAP synchronizations gone wrong.

`mdedup` cleans this up. Point it at your boxes: it groups copies of the same mail by hashing a curated set of headers, applies a `--strategy` to pick which copy to keep in each group, then performs an `--action` on the result. The default action is the safest one: sources are only read, and the deduplicated selection is written to a brand new box.

So to merge two overlapping archives into a single clean box:

```shell-session
$ mdedup --strategy select-one --export merged.mbox archive-2024.mbox archive-2025.mbox
```

Mails found in both archives are copied once into `merged.mbox`, along with all the mails that were unique to each source.

<p align="center">
  <img src="https://raw.githubusercontent.com/kdeldycke/mail-deduplicate/main/docs/assets/cli-coloured-run.png">
</p>

To remove duplicates in place instead, switch to a destructive action, and rehearse with `--dry-run`:

```shell-session
$ mdedup --strategy select-one --action delete-discarded --dry-run ~/Maildir
```

The [hands-on tutorial](https://kdeldycke.github.io/mail-deduplicate/tutorial.html) builds a small playground of duplicated mails, then walks through strategies, actions and safeguards on it. The [design page](https://kdeldycke.github.io/mail-deduplicate/design.html) explains how duplicates are detected.

> [!WARNING]
> Performance and memory usage: `mdedup` implementation is quite naive and everything resides in memory.
>
> If this is good enough for a volume of a couple of gigabytes, the more emails `mdedup` try to parse, the closer you'll reach the memory limits of your machine. In which case [`mdedup` will exit abruptly](https://github.com/kdeldycke/mail-deduplicate/issues/362#issuecomment-1266743045), zapped by the [OOM killer](https://en.wikipedia.org/wiki/Out_of_memory) of your OS. Of course your mileage may vary depending on your hardware.
>
> You can influence implementation of this feature with pull requests, [purchasing business support 🤝](https://github.com/sponsors/kdeldycke) and [sponsorship 🫶](https://github.com/sponsors/kdeldycke).
