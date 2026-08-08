# {octicon}`zap` Performance

How long a run takes, how much memory it holds, and how to make the next run faster.

Every timing below comes from one batch of runs on an Apple silicon SSD, over a synthetic maildir of 20,000 mails of about 4 KB each, one fifth of them exact duplicates. They are only meaningful against each other: the same corpus measures twice as slow on an x86 interpreter under Rosetta as on a native one, so read the proportions and the ratios, which held steady across every machine tried, rather than the seconds themselves. Counts of mails read are exact, and depend on your corpus alone.

## Where a run spends its time

Hashing dominates a first run, and the [hash cache](#reusing-hashes-between-runs) is the only thing that skips it. What is left over then becomes the bulk of the work:

| Step                    | First run  | With a warm cache | What it does                                                    |
| ----------------------- | ---------- | ----------------- | --------------------------------------------------------------- |
| 1. Loading mails        | 0.1s ( 3%) | 0.1s ( 6%)        | Lists each box. Cheap, but grows with the number of subfolders. |
| 2. Hashing              | 2.0s (59%) | 0.4s (23%)        | Reads and parses every mail.                                    |
| 3. Selecting duplicates | 1.1s (33%) | 1.2s (63%)        | Re-reads the body of every mail sharing its hash with another.  |
| 4. Performing actions   | 0.2s ( 5%) | 0.2s ( 8%)        | Writes, for every action but `delete-*` on the source box.      |
| **Total**               | **3.4s**   | **1.9s**          |                                                                 |

The cache cuts hashing by a factor of five, yet the run as a whole only gets twice as fast, because step 3 is left untouched and grows from a third of the run to nearly two thirds of it.

Step 3 is worth understanding: a mail is [dehydrated](design.md) once hashed, so comparing it against `--size-threshold` and `--content-threshold` pulls its body back from disk. Only mails sharing their hash with another are compared, so the cost tracks how many duplicates you actually have. On this corpus that is **8,000 of the 20,000 mails read a second time**, a count that does not depend on your hardware and is the number to reason about.

### Skipping the threshold comparisons

Both thresholds exist to catch mails that hash alike without being copies, so turning them off means acting on a set that was never checked. When you trust your hash, `-1` disables either one, and the re-reads go with them:

| Warm run, `--hash-body skip`   | Total | Mails re-read |
| ------------------------------ | ----- | ------------- |
| Default thresholds             | 1.9s  | 8,000         |
| `--content-threshold=-1` alone | 1.8s  | 8,000         |
| Both set to `-1`               | 1.0s  | 0             |

That middle row is the surprise: dropping the content check alone changes nothing under the default `--hash-body skip`. A mail's size is the length of its body, and skip mode never reads bodies while hashing, so the *size* check drags them back on its own.

Hash the body and that stops being true. `raw` and `normalized` compute each mail's size while hashing, so the cache stores it and the size check is served from the database:

| Warm run, `--hash-body raw`    | Total | Mails re-read |
| ------------------------------ | ----- | ------------- |
| Default thresholds             | 1.8s  | 8,000         |
| `--content-threshold=-1` alone | 1.0s  | 0             |

A body-hashing run therefore keeps its size safeguard for free, and only has to give up the content comparison to avoid the second pass entirely.

## Memory

A mail is reduced to a lightweight stub as soon as it is hashed, so memory tracks the *number* of mails rather than their size. About **600 bytes are retained per mail**, which a run's transient allocations round up to roughly 1 KB of resident memory.

```{note}
That figure assumes Python 3.11 or later. A stub is mostly its instance dictionary, and 3.11 made those share their keys between instances, so the same corpus retains close to twice as much on Python 3.10: about 1.1 KB per mail. Upgrading the interpreter is the cheapest way to halve the memory of a large run.
```

| Mails  | Box size | Peak resident memory |
| ------ | -------- | -------------------- |
| 1,500  | 215 MB   | 46 MB                |
| 20,000 | 79 MB    | 65 MB                |
| 60,000 | 235 MB   | 109 MB               |

The fixed baseline is around 43 MB of interpreter and imports, so a collection of 300,000 mails lands near 375 MB. Large enough collections can still reach the limits of your machine, in which case [`mdedup` exits abruptly](https://github.com/kdeldycke/mail-deduplicate/issues/362#issuecomment-1266743045), zapped by your OS's [OOM killer](https://en.wikipedia.org/wiki/Out_of_memory). Re-reading mail content also costs extra disk I/O, so your mileage varies with your hardware.

```{tip}
Deduplicating one box at a time keeps the peak lower than passing every box in a single run, since mails are only grouped across the sources of the same run.
```

## Hashing in parallel

`--jobs` fans the hashing out across worker threads. Reading stays single-threaded, because the box objects of Python's `mailbox` module are not safe for concurrent access, so only the hashing itself is parallelized.

```{warning}
On a stock interpreter, raising `--jobs` does not currently pay. Measured on the corpus above, the hashing step comes out at `0.88x` to `0.97x` of its single-job time whatever the `--hash-body` mode: a small net loss to thread contention and batching.

The reason is that what gets handed to the threads is Python-level work, which the global interpreter lock serializes anyway, while the reading and parsing that dominate the step stay on the main thread. A free-threaded interpreter lifts the lock but not the serial reading, and only reaches `1.37x` at eight jobs with `--hash-body normalized`.

Leave it at its default of `1` unless you have measured a gain on your own corpus. See [issue #87](https://github.com/kdeldycke/mail-deduplicate/issues/87) for the measurements and what would have to change.
```

## Reusing hashes between runs

The same mail, hashed with the same options, always produces the same result. `--cache` keeps those results in a local SQLite database so a later run skips reading and parsing the mails it has already seen.

```shell-session
$ mdedup --cache --strategy select-newest --action delete-discarded ~/Maildir
```

On the 20,000-mail corpus, a second run takes roughly half the time of an uncached one, `1.9s` against `3.4s`, and its hashing step alone is five times faster. The first run costs about 15% more than an uncached one, which is the price of filling the database.

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

| Platform              | Location                                                                      |
| --------------------- | ----------------------------------------------------------------------------- |
| macOS                 | `~/Library/Caches/mdedup/hashes.db`                                           |
| Linux and other POSIX | `$XDG_CACHE_HOME/mdedup/hashes.db`, defaulting to `~/.cache/mdedup/hashes.db` |
| Windows               | `%LOCALAPPDATA%\mdedup\Cache\hashes.db`                                       |

Run `mdedup --help` to see the resolved path on your machine. It holds about 135 bytes per mail, so 20,000 mails cost around 2.7 MB.

It prunes itself as it goes, so it tracks your mails rather than growing forever. Every run drops the entries of mails that disappeared from the boxes it opened, and the entries of every box that is no longer on disk at all. The count is reported at the end of the hashing step:

```text
Hash cache: 19,982 mails restored, 18 hashed and recorded, 143 stale entries dropped.
```

Boxes you did not pass on the command line are left alone: their mails are missing from a run's sightings because nobody looked, which is no evidence that they are gone.

Pruning frees space inside the database for later entries, but does not hand it back to your filesystem, so the file never shrinks on its own. Deleting it is always safe, and the next run rebuilds whatever it needs:

```shell-session
$ rm ~/.cache/mdedup/hashes.db
```

Nothing about the cache can take a run down. A database that cannot be opened, on a read-only or full filesystem for instance, is reported as a warning and skipped, and the run hashes every mail as it would without `--cache`. One that cannot be written at the end, because another run holds it or the disk filled up, costs only the next run its head start: by then the deduplication has already produced its results.

### Runs sharing a database

Several runs can point at the same database. They only contend on the single write burst each performs when its hashing step ends, which SQLite serializes: a run that finds the database busy waits up to 30 seconds for it, then gives up on writing and carries on. Reads never block.

## Body hashing

`--hash-body` decides whether mail bodies take part in the hash, and it is the single biggest lever on hashing cost after the cache.

| Mode         | 20,000 mails | Notes                                                                                |
| ------------ | ------------ | ------------------------------------------------------------------------------------ |
| `skip`       | `3.4s`       | The default. Headers alone are usually enough to identify duplicates.                |
| `raw`        | `3.7s`       | Hashes the body as it is.                                                            |
| `normalized` | `4.8s`       | Strips line breaks and spaces first, catching copies that differ only in whitespace. |

Reach for `raw` or `normalized` when header-based hashing groups mails you do not consider duplicates, rather than as a default.
