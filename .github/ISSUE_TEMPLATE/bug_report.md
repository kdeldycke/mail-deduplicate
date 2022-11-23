---
name: 🐛 Bug Report
about: Create a report to help improve the project
title: \U0001F41B <CHANGE BUG REPORT TITLE HERE>
labels: 🐛 bug
assignees: kdeldycke
---

#### Preliminary checks

- [ ] I am running the latest version
- [ ] I have [read the Code of Conduct](https://github.com/kdeldycke/mail-deduplicate/blob/develop/.github/code-of-conduct.md)
- [ ] I have checked there is not other [Issues](https://github.com/kdeldycke/mail-deduplicate/issues) or [Pull Requests](https://github.com/kdeldycke/mail-deduplicate/pulls) covering the same topic to open

#### Describe the bug

A clear and concise description of what the bug is.

#### To reproduce

Steps to reproduce the behavior:

1. The full `mdedup` CLI invocation you used.

   ```shell-session
   $ mdedup --verbosity=DEBUG ./my_maildir/
   ```

1. The data set leading to the bug.
   Try to produce here the minimal subset of mails leading to the bug, and add copies of those mails (eventually censored).
   This effort will help maintainers add this particular edge-case to the set of unittests to prevent future regressions.
   You can reduce down the issue to a particular deduplicate subset by using the `--hash-only` parameter.

#### Expected behavior

A clear and concise description of what you expected to happen.

#### CLI output

Add here the raw copy of some console output you were able to produce. Some exemple includes:

- The `mdedup` CLI invocation and its output:

```shell-session
$ mdedup --verbosity=DEBUG ./my_maildir/
(...)
  === Phase #1: load mails.
  === Phase #2: compute mail hashes.
  === Phase #3: deduplicate mails.
  ╒════════════╤══════════╕
  │ Mails      │   Metric │
  ╞════════════╪══════════╡
  │ Found      │        5 │
  ├────────────┼──────────┤
  │ Rejected   │        0 │
  ├────────────┼──────────┤
  │ Kept       │        5 │
  ├────────────┼──────────┤
  │ Unique     │        0 │
  ├────────────┼──────────┤
  │ Duplicates │        5 │
  ├────────────┼──────────┤
  │ Deleted    │        0 │
  ╘════════════╧══════════╛
  ╒══════════════════════════════════════╤══════════╕
  │ Duplicate sets                       │   Metric │
  ╞══════════════════════════════════════╪══════════╡
  │ Total                                │        2 │
  ├──────────────────────────────────────┼──────────┤
  │ Ignored                              │        0 │
  ├──────────────────────────────────────┼──────────┤
  │ Skipped                              │        2 │
  ├──────────────────────────────────────┼──────────┤
  │ Rejected (bad encoding)              │        0 │
  ├──────────────────────────────────────┼──────────┤
  │ Rejected (too dissimilar in size)    │        0 │
  ├──────────────────────────────────────┼──────────┤
  │ Rejected (too dissimilar in content) │        0 │
  ├──────────────────────────────────────┼──────────┤
  │ Deduplicated                         │        0 │
  ╘══════════════════════════════════════╧══════════╛
```

- The Python traceback you encountered:

```python-tb
Traceback (most recent call last):
  File "/Users/kde/Library/Caches/pypoetry/virtualenvs/mail-deduplicate-x4bGukRb-py3.8/lib/python3.8/site-packages/click/testing.py", line 329, in invoke
    cli.main(args=args or (), prog_name=prog_name, **extra)
  File "/Users/kde/Library/Caches/pypoetry/virtualenvs/mail-deduplicate-x4bGukRb-py3.8/lib/python3.8/site-packages/click/core.py", line 782, in main
    rv = self.invoke(ctx)
  File "/Users/kde/Library/Caches/pypoetry/virtualenvs/mail-deduplicate-x4bGukRb-py3.8/lib/python3.8/site-packages/click/core.py", line 1066, in invoke
    return ctx.invoke(self.callback, **ctx.params)
  File "/Users/kde/Library/Caches/pypoetry/virtualenvs/mail-deduplicate-x4bGukRb-py3.8/lib/python3.8/site-packages/click/core.py", line 610, in invoke
    return callback(*args, **kwargs)
  File "/Users/kde/Library/Caches/pypoetry/virtualenvs/mail-deduplicate-x4bGukRb-py3.8/lib/python3.8/site-packages/click/decorators.py", line 21, in new_func
    return f(get_current_context(), *args, **kwargs)
  File "/Users/kde/mail-deduplicate/mail_deduplicate/cli.py", line 255, in mdedup
    dedup.check_stats()
  File "/Users/kde/mail-deduplicate/mail_deduplicate/deduplicate.py", line 645, in check_stats
    assert self.stats["mail_found"] >= self.stats["mail_kept"]
AssertionError:
```

- The `mdedup` output, but this time the `--verbosity=DEBUG` parameter:

```shell-session
$ mdedup --verbosity=DEBUG ./my_maildir/
(...)
--- 2 mails sharing hash c47ac7d8a9c3f103ca756dfb8b789527c0119d67b10b71d0a951c405
debug: <DuplicateSet hash=c47ac7d8a9c3f103ca756dfb8b789527c0119d67b10b71d0a951c405, size=2, conf=<mail_deduplicate.Config object at 0x7f5fab8c40d0>, pool=frozenset({<mail_deduplicate.mail.Mail object at 0x7f5faa3df0a0>, <mail_deduplicate.mail.Mail object at 0x7f5faa3b8070>})> created.
Check that mail differences are within the limits.
Skip checking for size differences.
Skip checking for content differences.
debug: Call delete_smaller() strategy.
Deleting all mails strictly smaller than 627 bytes...
0 candidates found for deletion.
Skip set: no deletion happened.
debug: <DuplicateSet hash=d44f163c514f6a454c4cf080fe8609040dd10ba3728376487d614538, size=2, conf=<mail_deduplicate.Config object at 0x7f5fab8c40d0>, pool=frozenset({<mail_deduplicate.mail.Mail object at 0x7f5faa3f5700>, <mail_deduplicate.mail.Mail object at 0x7f5faa3d8460>})> created.
Check that mail differences are within the limits.
Skip checking for size differences.
Skip checking for content differences.
debug: Call delete_smaller() strategy.
Deleting all mails strictly smaller than 2239 bytes...
0 candidates found for deletion.
Skip set: no deletion happened.
(...)
```

Wisely choose to feature here the full output or excerpt relevant to the bug you're trying to highlight.

#### Environment

All data on execution context as provided by `$ mdedup --version`:

```shell-session
$ mdedup --version
mdedup 6.0.0
{'username': '-', 'guid': '7f3fc29e62ad41e5335b6aa85b3eab9', 'hostname': '-', 'hostfqdn': '-', 'uname': {'system': 'Darwin', 'node': '-', 'release': '19.6.0', 'version': 'Darwin Kernel Version 19.6.0: Mon Aug 31 22:12:52 PDT 2020; root:xnu-6153.141.2~1/RELEASE_X86_64', 'machine': 'x86_64', 'processor': 'i386'}, 'linux_dist_name': '', 'linux_dist_version': '', 'cpu_count': 4, 'fs_encoding': 'utf-8', 'ulimit_soft': 256, 'ulimit_hard': 9223372036854775807, 'cwd': '-', 'umask': '0o2', 'python': {'argv': '-', 'bin': '-', 'version': '3.8.5 (default, Jul 21 2020, 10:48:26) [Clang 11.0.3 (clang-1103.0.32.62)]', 'compiler': 'Clang 11.0.3 (clang-1103.0.32.62)', 'build_date': 'Jul 21 2020 10:48:26', 'version_info': [3, 8, 5, 'final', 0], 'features': {'openssl': 'OpenSSL 1.1.1g  21 Apr 2020', 'expat': 'expat_2.2.8', 'sqlite': '3.33.0', 'tkinter': '8.5', 'zlib': '1.2.11', 'unicode_wide': True, 'readline': True, '64bit': True, 'ipv6': True, 'threading': True, 'urandom': True}}, 'time_utc': '2020-10-09 15:07:34.199095', 'time_utc_offset': 1.0, '_eco_version': '1.0.1'}
```

#### Additional context

Add any other context about the problem here.
