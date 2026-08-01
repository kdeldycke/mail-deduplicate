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

## Step 3: Selecting duplicates

Once all mails have been hashed, mails with the same hash are grouped together as duplicates. Then a selection strategy is applied to each group of duplicates to select which mails will be acted upon.

Several strategies can be chained into a fallback cascade by repeating the `--strategy` option. Each group is submitted to the first strategy, and handed over to the next each time a strategy fails to discriminate its mails: because it selected all of them, none of them, or could not compare mails missing a timestamp. The group is only skipped once the whole cascade is exhausted. A cascade ending with one of the random strategies, which always succeed, resolves the byte-identical copies that time-based and size-based criteria cannot tell apart.

### ❎ Safeguard: size threshold

Sets of duplicates are verified by comparing the body sizes of every pair of mails they contain, and pairs differing by more than a threshold are not considered copies of each other.

Since we're ignoring the `Content-Length` header by default [because of mailing-list effects](https://kdeldycke.github.io/mail-deduplicate/design.html#default-headers-and-mailing-lists), we introduced a limit on the allowed difference between the sizes of the message payloads.

If this threshold is exceeded, this could point to message corruption somewhere, or a false positive. The mails involved in the most offending pairs are then set aside with a warning naming them, so a single outlier does not prevent the deduplication of the true copies sharing its set. Every mail still acted upon is within the thresholds of all the other mails of its reduced set. When fewer than 2 similar mails remain, there is nothing coherent left to deduplicate and the whole set is skipped, with a warning.

```{caution}
Headers are not counted towards this threshold, because many [headers can be added by mailing list software](https://kdeldycke.github.io/mail-deduplicate/design.html#default-headers-and-mailing-lists) such as `mailman`, or even by the process of sending the mail through various MTAs.

One copy could have been stored by the sender's MUA prior to sending, without any `Received` headers, and another copy could be reflected back via a `CC`-to-self mechanism or mailing list server.

This threshold has to be large enough to allow for footers added by mailing list servers.
```

The default size threshold is **512 bytes**, and can be changed via the `--size-threshold` option.

### ❎ Safeguard: content threshold

Similarly to the size threshold, we generate unified diffs of duplicates and ensure that the diff is not greater than a certain size to limit false-positives.

The default content threshold is **768 bytes**, and can be changed via the `--content-threshold` option.

## Step 4: Performing actions

Once duplicates have been selected, an action is performed on them.
