# {octicon}`meter` Performance

How long a run takes, how much memory it holds, and how to make the next run faster.

All the figures below were measured on an Apple silicon SSD, over a synthetic maildir of 20,000 mails of about 4 KB each, one fifth of them exact duplicates. Yours will differ with your hardware, the size of your mails and how many of them are duplicates, but the shape of the costs holds.

## Where a run spends its time

Hashing dominates. On the corpus above it is around 60% of the run, and it is the only step the [hash cache](#reusing-hashes-between-runs) can skip.

| Step | Cost |
| --- | --- |
| 1. Loading mails | Listing each box. Cheap, but grows with the number of subfolders. |
| 2. Hashing | Reads and parses every mail. The bulk of the run. |
| 3. Selecting duplicates | Re-reads the body of every mail in a set of two or more, to compare them against the thresholds. |
| 4. Performing actions | Writes, for every action but `delete-*` on the source box. |

Step 3 is worth understanding: a mail is [dehydrated](design.md) once hashed, so comparing bodies against `--size-threshold` and `--content-threshold` pulls each one back from disk. Mails that end up alone in their hash group are never re-read, so the cost tracks how many duplicates you actually have. Setting both thresholds to `-1` skips those comparisons entirely, at the price of the safeguards they provide.

## Memory

A mail is reduced to a lightweight stub as soon as it is hashed, so memory tracks the *number* of mails rather than their size. About **600 bytes are retained per mail**, which a run's transient allocations round up to roughly 1 KB of resident memory.

```{note}
That figure assumes Python 3.11 or later. A stub is mostly its instance dictionary, and 3.11 made those share their keys between instances, so the same corpus retains close to twice as much on Python 3.10: about 1.1 KB per mail. Upgrading the interpreter is the cheapest way to halve the memory of a large run.
```

| Mails | Box size | Peak resident memory |
| --- | --- | --- |
| 1,500 | 215 MB | 46 MB |
| 20,000 | 79 MB | 65 MB |
| 60,000 | 235 MB | 109 MB |

The fixed baseline is around 43 MB of interpreter and imports, so a collection of 300,000 mails lands near 375 MB. Large enough collections can still reach the limits of your machine, in which case the OS will kill the process.

```{tip}
Deduplicating one box at a time keeps the peak lower than passing every box in a single run, since mails are only grouped across the sources of the same run.
```

## Hashing in parallel

`--jobs` fans the hashing out across worker threads. Reading stays single-threaded, because the box objects of Python's `mailbox` module are not safe for concurrent access, so only the hashing itself is parallelized. The speedup is therefore largest with `--hash-body raw` or `normalized`, where hashing does real work, and modest with the default `--hash-body skip`.

## Reusing hashes between runs

The same mail, hashed with the same options, always produces the same result. `--cache` keeps those results in a local SQLite database so a later run skips reading and parsing the mails it has already seen.

```shell-session
$ mdedup --cache --strategy select-newest --action delete-discarded ~/Maildir
```

On the 20,000-mail corpus, a second run drops from `4.3s` to `2.5s`. The first run costs about 16% more than an uncached one, which is the price of filling the database.

It is off by default. `--cache-path` points at another database and enables it on its own.

### What invalidates an entry

Two independent guards decide whether an entry can still be trusted.

**The options feeding the hash.** `--hash-header`, `--hash-body` and `--time-source` are fingerprinted together. Changing any of them discards the whole database, since an entry produced under different options cannot be told apart from a valid one.

**The file backing the mail.** Its size and modification time are recorded, and re-checked before the entry is used. What this covers depends on the box structure:

- Folder-based boxes (`maildir`, `MH`, `eml`) give each mail its own file, so the key tracks that mail alone. Editing one mail invalidates only that mail. Maildir flag changes, like marking a mail read, rename the file but keep its identity, so they do not needlessly invalidate anything.
- File-based boxes (`mbox`, `babyl`, `mmdf`) pack every mail into the box's single file, and identify them by byte offsets that shift as soon as a mail is added or removed. Any edit to the box therefore invalidates all of its mails at once.

Mails rejected for having [too few headers](design.md) are never cached, as that verdict depends on more than the hash.

### Dry runs fill the cache

`--dry-run` writes to the cache like any other run. This is deliberate, and it is the recommended way to work:

```shell-session
$ mdedup --cache --strategy select-newest --action delete-discarded --dry-run ~/Maildir
$ mdedup --cache --strategy select-newest --action delete-discarded ~/Maildir
```

Previewing what a run would do is exactly when you want to inspect the report, adjust your options and try again. Because the preview has already paid for the hashing, every subsequent run over the same mails is fast, including the real one. Nothing about the mails is modified: the cache lives outside your mail boxes.

```{caution}
The cache only ever spares the hashing step. It does not reduce memory, and it does not spare the body comparisons of step 3.
```

### Managing the database

The database sits in your platform's cache directory:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Caches/mdedup/hashes.db` |
| Linux and other POSIX | `$XDG_CACHE_HOME/mdedup/hashes.db`, defaulting to `~/.cache/mdedup/hashes.db` |
| Windows | `%LOCALAPPDATA%\mdedup\Cache\hashes.db` |

Run `mdedup --help` to see the resolved path on your machine. It holds about 135 bytes per mail, so 20,000 mails cost around 2.7 MB.

Nothing prunes it: entries for boxes you no longer have will accumulate. Deleting the file is always safe, and the next run rebuilds whatever it needs:

```shell-session
$ rm ~/.cache/mdedup/hashes.db
```

A database that cannot be opened, on a read-only or full filesystem for instance, is reported as a warning and skipped. The run carries on hashing every mail, as it would without `--cache`.

## Body hashing

`--hash-body` decides whether mail bodies take part in the hash, and it is the single biggest lever on hashing cost after the cache.

| Mode | 20,000 mails | Notes |
| --- | --- | --- |
| `skip` | `4.3s` | The default. Headers alone are usually enough to identify duplicates. |
| `raw` | `5.4s` | Hashes the body as it is. |
| `normalized` | `6.9s` | Strips line breaks and spaces first, catching copies that differ only in whitespace. |

Reach for `raw` or `normalized` when header-based hashing groups mails you do not consider duplicates, rather than as a default.
