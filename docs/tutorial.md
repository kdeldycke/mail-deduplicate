# {octicon}`mortar-board` Tutorial

This page walks through a complete deduplication run on two tiny mail boxes built for the occasion, so you can rehearse every command in a sandbox before pointing `mdedup` at your precious archives.

## Where duplicates come from

Duplicate mails are rarely typed twice: they are copies accumulated by the tools around them.

- Backups of the same account taken at different times, each holding a copy of the older mails.
- Per-folder or per-label exports, where a mail filed under several labels lands in several boxes.
- Archives consolidated from multiple clients or machines over the years.
- IMAP synchronization accidents, where an interrupted or misconfigured sync re-uploads mails.
- Mailing lists reflecting back mails you also keep in your sent box, slightly altered by footers or subject prefixes.

That last case is why `mdedup` does not blindly compare raw files: mails are grouped by a hash of a [curated set of headers](https://kdeldycke.github.io/mail-deduplicate/design.html#default-headers-and-mailing-lists), so two copies can differ in transport details and still be recognized as the same mail.

## Build a playground

Save this script as `make_playground.py`. It creates two overlapping `mbox` archives, mimicking two backups of the same account taken a year apart:

```python
import mailbox
from email.message import EmailMessage


def make_mail(subject, date, msg_id, body):
    mail = EmailMessage()
    mail["From"] = "news@example.com"
    mail["To"] = "me@example.com"
    mail["Subject"] = subject
    mail["Date"] = date
    mail["Message-ID"] = msg_id
    mail.set_content(body)
    return mail


# Two mails present in both archives: these are the duplicates.
shared = [
    make_mail(
        "Weekly digest",
        "Mon, 05 Feb 2024 09:00:00 +0000",
        "<digest-2024-02-05@example.com>",
        "This week's news.\n",
    ),
    make_mail(
        "Server maintenance window",
        "Wed, 03 Apr 2024 17:30:00 +0000",
        "<maintenance-2024-04-03@example.com>",
        "The server will be down on Friday.\n",
    ),
]

# Mails unique to each archive.
only_2024 = [
    make_mail(
        "Invoice January",
        "Wed, 31 Jan 2024 12:00:00 +0000",
        "<invoice-2024-01@example.com>",
        "Your invoice is attached.\n",
    ),
]
only_2025 = [
    make_mail(
        "Weekly digest",
        "Mon, 03 Feb 2025 09:00:00 +0000",
        "<digest-2025-02-03@example.com>",
        "This week's news, a year later.\n",
    ),
    make_mail(
        "Password reset",
        "Tue, 11 Mar 2025 08:15:00 +0000",
        "<reset-2025-03-11@example.com>",
        "Click the link to reset your password.\n",
    ),
]

for path, mails in (
    ("archive-2024.mbox", shared + only_2024),
    ("archive-2025.mbox", shared + only_2025),
):
    box = mailbox.mbox(path)
    for mail in mails:
        box.add(mailbox.mboxMessage(mail))
    box.flush()
    box.close()
    print(f"{path}: {len(mails)} mails")
```

Run it from an empty working folder:

```shell-session
$ python make_playground.py
archive-2024.mbox: 3 mails
archive-2025.mbox: 4 mails
```

That is 7 mails in total, of which only 5 are distinct. Notice the trap laid for naive matchers: the two archives each contain a *different* "Weekly digest" mail, sent a year apart. A deduplicator keying on subjects alone would wrongly collapse them.

## Take stock, without a strategy

Your first instinct might be to just feed both boxes to `mdedup`:

```shell-session
$ mdedup --export merged.mbox archive-2024.mbox archive-2025.mbox
(...)
● Step #3 - Select mails in each group
warning: No strategy configured, skip selection.
info: ◼ 2 mails sharing hash 68125abccc1b04c54f5922415b0d8c258630374d4183b1b00bc0717b
info: Check mail differences are below the thresholds.
warning: Skip set: no strategy to apply.
info: ◼ 2 mails sharing hash 27002f26e42a10bd0046ec327a54a5547b7ea99b4b38bab4fc5b01dd
info: Check mail differences are below the thresholds.
warning: Skip set: no strategy to apply.
(...)
│ Found      │ 7      │ Total number of mails encountered from all mail sources.     │
(...)
│ Duplicates │ 4      │ Number of duplicate mails (sum of mails in all duplicate     │
│            │        │ sets with at least 2 mails).                                 │
│ Skipped    │ 4      │ Number of mails ignored in the selection step because the    │
│            │        │ whole set they belong to was skipped.                        │
(...)
│ Skipped - Strategy │ 2      │ Number of sets skipped from the selection process because  │
│                    │        │ the strategy could not be applied.                         │
│ Deduplicated       │ 0      │ Number of valid sets on which the selection strategy was   │
│                    │        │ successfully applied.                                      │
(...)
```

The run went fine, yet ended with `Deduplicated: 0`. This is `mdedup` being cautious, not broken: it did detect the 2 duplicate pairs (`Duplicates: 4` mails), but it refuses to guess which copy of each pair you want to keep. Without a `--strategy`, every duplicate set is skipped, and only the mails without copies end up in `merged.mbox`.

Delete that incomplete `merged.mbox` before moving on, as `mdedup` will refuse to overwrite an existing box:

```shell-session
$ rm merged.mbox
```

## Choose a strategy

A strategy decides, within each set of copies, which mails are *selected* and which are *discarded*. Strategies come in mirrored pairs (`select-oldest` is `discard-newer`, and so on), and in a few families:

- Time-based: `select-oldest`, `select-newest` and friends, comparing dates.
- Size-based: `select-smallest`, `select-biggest` and friends, comparing mail sizes.
- Path-based: `select-matching-path` and friends, testing mail locations against `--regexp`.
- Random: `select-one` and `select-all-but-one`, for when copies are indistinguishable.

The full list, with the exact semantics of each, sits at the bottom of `mdedup --help` and in the [CLI parameters page](https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html).

Backup copies of the same mail are usually byte-identical: same `Date` header, same size. Time-based and size-based strategies cannot tell such copies apart, and skip the set as a whole rather than acting on it. That makes `select-one`, which keeps an arbitrary copy of each mail, the right strategy for merging identical copies.

## Merge into a clean box

Now for the real run. `--strategy select-one` picks one copy per set, and the default action (`copy-selected`) writes every selected mail to the `--export` box, leaving the sources untouched:

```shell-session
$ mdedup --strategy select-one --export merged.mbox archive-2024.mbox archive-2025.mbox
(...)
● Step #3 - Select mails in each group
info: select-one strategy will be applied on each duplicate set to select candidates.
info: ◼ 2 mails sharing hash 68125abccc1b04c54f5922415b0d8c258630374d4183b1b00bc0717b
info: Check mail differences are below the thresholds.
info: Apply select-one strategy...
info: Randomly select one duplicate...
info: 1 mail candidates selected for action.
(...)
● Step #4 - Perform action on selected mails
info: Perform copy-selected action...
info: 5 mails selected for action.
info: Creating new mbox box at merged.mbox ...
(...)
│ Unique     │ 3      │ Number of unique mails (which were automatically added to    │
│            │        │ selection).                                                  │
(...)
│ Discarded  │ 2      │ Number of mails discarded from the final selection.          │
│ Selected   │ 2      │ Number of mails kept in the final selection on which the     │
│            │        │ action will be performed.                                    │
│ Copied     │ 5      │ Number of mails copied from their original mailbox to        │
│            │        │ another.                                                     │
(...)
│ Deduplicated       │ 2      │ Number of valid sets on which the selection strategy was   │
│                    │        │ successfully applied.                                      │
(...)
```

Read the report bottom-up: both duplicate sets were deduplicated, one copy of each was selected and the other discarded, and the 2 selected mails were copied to `merged.mbox` together with the 3 unique mails. 7 mails in, 5 mails out, nothing lost:

```shell-session
$ grep --count "^From " merged.mbox
5
```

Both "Weekly digest" mails made it through, as their different `Date` and `Message-ID` headers put them in different sets.

```{tip}
The export box defaults to the `mbox` format. Pass `--export-format maildir` to produce a `maildir` folder instead, ready to be dropped on an IMAP server or opened by any client.
```

## Delete duplicates in place

Copying is the safe default, but sometimes you want to prune the originals: say the mails in `archive-2025.mbox` are the canonical ones, and any copy of them lingering in `archive-2024.mbox` should go.

Path-based strategies handle this preference: `select-matching-path` keeps the copies whose location matches `--regexp`, so the `delete-discarded` action removes the copies living elsewhere. Destructive actions deserve a rehearsal first:

```shell-session
$ mdedup --strategy select-matching-path --regexp 2025 --action delete-discarded --dry-run archive-2024.mbox archive-2025.mbox
(...)
● Step #4 - Perform action on selected mails
info: Perform delete-discarded action...
info: 5 mails selected for action.
warning: DRY RUN: Skip action.
warning: DRY RUN: Skip action.
(...)
```

Two deletions planned, as expected: the two shared mails, in their `archive-2024.mbox` incarnation. Do not let the `5 mails selected` line worry you: it counts the mails that will survive, while the action itself only touches the 2 discarded copies. Drop `--dry-run` to proceed:

```shell-session
$ mdedup --strategy select-matching-path --regexp 2025 --action delete-discarded archive-2024.mbox archive-2025.mbox
(...)
info: <mboxDedupMail archive-2024.mbox:1> deleted.
info: <mboxDedupMail archive-2024.mbox:0> deleted.
(...)
$ grep --count "^From " archive-2024.mbox
1
$ grep --count "^From " archive-2025.mbox
4
```

`archive-2024.mbox` is down to its single unique mail, and `archive-2025.mbox` was not touched. Mails without duplicates are never deleted, whatever the strategy: only discarded members of a duplicate set are.

```{caution}
For folder-based boxes (`maildir`, `mh`), `--regexp` is tested against the path of each individual mail file. For file-based boxes (`mbox`, `babyl`, `mmdf`), all mails share the path of the box itself.
```

## Safety nets

Several safeguards run before any mail is acted upon, each detailed in the [design page](https://kdeldycke.github.io/mail-deduplicate/design.html):

- Mails with too few of the hashed headers are rejected as unparsable instead of being trusted.
- Mails in a set differing too much in size or content are considered suspicious: the whole set is skipped. The `--size-threshold` and `--content-threshold` options tune these limits, and `--show-diff` prints the offending differences.
- A strategy that would select all mails of a set, or none, leaves the set untouched.
- Unique mails are always part of the final selection, so a merge never drops them.

## When nothing gets deduplicated

A run ending with `Duplicates: 0` or `Deduplicated: 0` is the number one source of confusion, so map the statistics report to its cause:

- `Duplicates: 0`: no two mails shared a hash. A single box that was never merged or re-synced typically holds no duplicates: `mdedup` shines on piles of overlapping boxes. If you are certain copies are in there, they may differ in the hashed headers: mails re-delivered or forwarded can get a new `Message-ID` for instance. Narrow the matching down with repeated `--hash-header` options, or inspect what each mail hashes to with `--hash-only`.
- `Duplicates` above zero but `Skipped - Strategy` counting sets: either no `--strategy` was given, or the chosen criterion cannot split the copies apart (identical copies share the same date and size). Switch to `select-one`, or to a path-based strategy.
- `Skipped - Size` or `Skipped - Content` counting sets: mails grouped under the same hash differ more than the thresholds allow. Inspect with `--show-diff`, and raise `--size-threshold` or `--content-threshold` deliberately if the differences are legitimate.

## Going further

- Every option demonstrated here is described in the [CLI parameters page](https://kdeldycke.github.io/mail-deduplicate/cli-parameters.html).
- Recurring options can be saved in a [configuration file](https://kdeldycke.github.io/mail-deduplicate/configuration.html).
- The [design page](https://kdeldycke.github.io/mail-deduplicate/design.html) details hashing, header normalization and the safeguards.
- Header-based hashing can be complemented by body hashing for stricter matching: see `--hash-body`, and `--jobs` to parallelize it on big boxes.
