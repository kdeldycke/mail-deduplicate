# {octicon}`light-bulb` Design

This CLI reads mails, then automatically detects, regroup and act on duplicates.

Process:

- Step #1: load mails from their sources.
- Step #2: compute the canonical hash of each mail based on their headers (and optionally their body), and regroup mails sharing the same hash.
- Step #3: apply a selection strategy on each subset of duplicate mails.
- Step #4: perform an action on all selected mails.
- Step #5: report statistics.

For added protection against accidentally removing mails due to false positives, we introduced several safeguards along the processing steps which can be configured via CLI options.

## Step 1: Loading mails

Mails are loaded from a variety of mailbox formats (`maildir`, `mbox`, `babyl`, `mh`, `mmdf` and `eml`).

## Step 2: Hashing

In theory, we could rely on the mail's `Message-ID` as a key to identify duplicate mails.

The reality is messier. There is no guarantee that `Message-ID` is unique or even present. Yes, certain broken mail servers which must remain nameless are guilty of this. 😩

That is why `mdedup` propose to identify uniqueness of mails based on an ordered hashed list of headers.

Hashing is done by cherry-picking certain headers, in some cases doing some minor tweaking of the values to reduce them to a canonical form, and then computing a hash of those headers concatenated together.

The list of headers to consider can be set with the `-h`/`--hash-header` option.

```{tip}
You can use `Message-ID` as the sole reference header by passing `--hash-header Message-ID` to the CLI.
```

Once a mail is hashed it is dehydrated: its parsed message is dropped, and only its identity, its source box and a few memoized scalars are retained. Even its own location is derived from its box on demand rather than stored. The steps below re-read from the source box whatever content they need, so the memory held for the rest of the run amounts to about 600 bytes per mail, whatever the size of the boxes.

### Default headers and mailing lists

The [default headers](https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.cli.DEFAULT_HASH_HEADERS) used for hashing are currently set to:

- `Date`
- `From`
- `To`
- `Subject`
- `MIME-Version`
- `Content-Type`
- `Content-Disposition`
- `User-Agent`
- `X-Priority`
- `Message-ID`

This set was crafted to limit the effects of mailing-lists on both the mail headers and body, including:

- having an extra footer in the mail's body, thus changing the `Content-Length` header;
- mails with a new path described by the `Received` headers which would not be contained in any copy of the mail saved locally at the time it was sent to the list;
- munging the `Reply-To` header even though it's a bad idea;
- adding plenty of other random headers which a copy saved locally at sending-time would not have, such as `X-Mailman-Version`, `Precedence`, `X-BeenThere`, `List-*`, `Sender`, `Errors-To`, and so on;
- adding a prefix to the `Subject` header.

### ❎ Safeguard: minimal headers

To avoid hashing mails with too few headers (like corrupted mails), a minimal number of the selected headers must be present in a mail before its hash is trusted.

This floor is derived automatically as the smaller of **4** and the number of headers selected via `--hash-header`. The default ten-header set therefore requires at least four to be present, while narrowing the selection down to a single header relaxes the floor to match, so no dedicated option is needed.

### Reusing hashes between runs

Hashing the same mail with the same options always produces the same result, so `--cache` keeps those results in a local database and lets a later run skip reading and parsing the mails it has already seen. Its invalidation rules and the cost of each hashing option are covered in [](performance.md).

## Step 3: Selecting duplicates

Once all mails have been hashed, mails with the same hash are grouped together as duplicates. Then a selection strategy is applied to each group of duplicates to select which mails will be acted upon.

Several strategies can be chained into a fallback cascade by repeating the `--strategy` option. Each group is submitted to the first strategy, and handed over to the next each time a strategy fails to discriminate its mails: because it selected all of them, none of them, or could not compare mails missing a timestamp. The group is only skipped once the whole cascade is exhausted. A cascade ending with one of the random strategies, which always succeed, resolves the byte-identical copies that time-based and size-based criteria cannot tell apart.

### ❎ Safeguard: size threshold

Sets of duplicates are verified by comparing the body sizes of the mails they contain, and two mails differing by more than a threshold are not considered copies of each other.

Since we're ignoring the `Content-Length` header by default [because of mailing-list effects](https://kdeldycke.github.io/mail-deduplicate/design.html#default-headers-and-mailing-lists), we introduced a limit on the allowed difference between the sizes of the message payloads.

If this threshold is exceeded, this could point to message corruption somewhere, or a false positive. The mails involved in the most offending pairs are then set aside with a warning naming them, so a single outlier does not prevent the deduplication of the true copies sharing its set. Every mail still acted upon is within the thresholds of all the other mails of its reduced set. When fewer than 2 similar mails remain, there is nothing coherent left to deduplicate and the whole set is skipped, with a warning.

```{caution}
Headers are not counted towards this threshold, because many [headers can be added by mailing list software](https://kdeldycke.github.io/mail-deduplicate/design.html#default-headers-and-mailing-lists) such as `mailman`, or even by the process of sending the mail through various MTAs.

One copy could have been stored by the sender's MUA prior to sending, without any `Received` headers, and another copy could be reflected back via a `CC`-to-self mechanism or mailing list server.

This threshold has to be large enough to allow for footers added by mailing list servers.
```

The default size threshold is **512 bytes**, and can be changed via the `--size-threshold` option. Set it to `0` to demand copies of exactly the same size, or to `-1` to drop the check. Dropping it leaves the hash as the only evidence that two mails are copies.

### ❎ Safeguard: content threshold

Similarly to the size threshold, we generate unified diffs of duplicates and ensure that the diff is not greater than a certain size to limit false-positives.

The default content threshold is **768 bytes**, and can be changed via the `--content-threshold` option. Its `0` and `-1` values mean what they mean for the size threshold.

## Step 4: Performing actions

Once duplicates have been selected, an action is performed on them.

### Reading a strategy against an action

A strategy names the half of each set it selects, and an action names the half it applies to. The two are chosen apart, so read them together before running anything destructive.

`--strategy select-newest --action delete-discarded` keeps the newest copy of each set and removes the others. Swapping the action for `delete-selected` removes the newest copy and keeps the others. Both are valid requests, and only one of them is usually the intended one. The same holds for the `discard-*` strategies, which name the opposite half: `--strategy discard-newest --action delete-selected` also keeps the newest copy.

`--dry-run` reports what either pairing would do without touching a mail, which settles the question in one run.

### Mails without duplicates

A mail alone in its duplicate set has no copy to be compared to, so no strategy ever rules on it. It is kept, and belongs to the selection the `*-selected` actions target: this is what makes `--action copy-selected` and `--action move-selected` produce a box holding the whole deduplicated corpus, and not its duplicates only.

`--action delete-selected` is the one exception, and leaves those mails in place. Deleting one removes the only copy of it there is, and nothing was written anywhere else first. The deletion therefore applies to the mails a strategy really picked, and the report says how many were left untouched.

### Hardlinking duplicates

`--action hardlink-discarded` is the one action that neither removes a mail nor writes it somewhere else: each discarded mail stays in its folder, under its own name, but the file backing it is replaced by a hardlink to the copy kept in its own duplicate set. The copies then share a single file on disk, and the space the others took is reclaimed.

This is aimed at the same mail reaching several accounts or folders, where each copy carries the headers it collected on its own way in. Files that are already identical byte for byte are the province of general-purpose tools like [`duperemove`](https://github.com/markfasheh/duperemove) or [`hardlink`](https://jak-linux.org/projects/hardlink/), which scan a whole filesystem. What those cannot decide is whether two files that differ are the same *mail*: that is the question the hashing and selection steps above answer.

Two properties make this safe to run on a live mail store:

- The link is created under a temporary name in the mail's own directory and then renamed over it. The rename is atomic and stays on one filesystem by construction, so the mail is never missing from its box, whatever interrupts the run.
- The mail keeps its file name, which is where `maildir` records its flags. The same mail can stay read in one folder and unread in another while both share one file.

A mail is left untouched, and counted apart in the report, when it comes from a file-based box (`mbox`, `babyl` and `mmdf` pack every mail into the box's single file, so none has a file of its own to link), when it already shares the file of the copy kept, or when it sits on another filesystem. Re-running over an already-linked box is therefore a no-op.

By default only copies that are identical byte for byte are linked. Linking a mail that differs swaps its content for the kept copy's, which reads as a deduplication but is really a rewrite: whatever was unique to that copy is gone, and nothing on disk records that it changed. That is the interesting case for mails delivered to several accounts, so `--hardlink-differing` enables it, as a deliberate choice rather than a default. The size and content thresholds described above still gate which mails reach this step at all.

```{caution}
Linked mails share one inode, and so share the permissions, ownership and modification time of the copy kept. A mail client that rewrites a mail in place rather than replacing it, which the `maildir` specification tells it not to do, would alter every copy at once.
```
