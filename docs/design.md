# {octicon}`light-bulb` Design

This CLI reads all mails from a variety of mailbox formats (`maildir`, `mbox`, `babyl`, `mh` and `mmdf`), then automatically detects, regroup and act on duplicates.

Duplicate detection is done by cherry-picking certain headers, in some cases doing some minor tweaking of the values to reduce them to a canonical form, and then computing a hash of those headers concatenated together.

## Hashing headers

In theory, we could rely on the mail's `Message-ID` as a key to identify duplicate mails.

The reality is messier. There is no guarantee that `Message-ID` is unique or even present. Yes, certain broken mail servers which must remain nameless are guilty of this. 😩

That is why `mdedup` propose to identify uniqueness of mails based on an ordered hashed list of headers.

The list of headers to consider can be set with the `-h`/`--hash-header` option.

```{tip}
You can still use `Message-ID` as the sole reference header by passing `--hash-header Message-ID --minimal-headers 1` to the CLI.
```

## Mailing lists

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

## Safeguards against false positives

For added protection against accidentally removing mails due to false positives, we introduced several safeguards which can be configured via CLI options.

### Minimal headers

To avoid hashing mails with too few headers (e.g., corrupted mails), we introduced a minimal number of headers required to compute a hash.

By default, this minimal number of headers is set to **4**. It can be changed via the `--minimal-headers` option.

### Size threshold

Sets of duplicates are verified by comparing body sizes, and if they differ by more than a threshold, they are not counted as duplicates and the whole set is skipped with a warning.

Since we're ignoring the `Content-Length` header by default [because of mailing-list effects](https://kdeldycke.github.io/mail-deduplicate/design.html#mailing-lists), we introduced a limit on the allowed difference between the sizes of the message payloads.

If this threshold is exceeded, a warning is issued and the messages are not considered duplicates, because this could point to message corruption somewhere, or a false positive.

```{caution}
Headers are not counted towards this threshold, because many [headers can be added by mailing list software](https://kdeldycke.github.io/mail-deduplicate/design.html#mailing-lists) such as `mailman`, or even by the process of sending the mail through various MTAs.

One copy could have been stored by the sender's MUA prior to sending, without any `Received` headers, and another copy could be reflected back via a `CC`-to-self mechanism or mailing list server.

This threshold has to be large enough to allow for footers added by mailing list servers.
```

The default size threshold is **512 bytes**, and can be changed via the `--size-threshold` option.

### Content threshold

Similarly to the size threshold, we generate unified diffs of duplicates and ensure that the diff is not greater than a certain size to limit false-positives.

The default content threshold is **768 bytes**, and can be changed via the `--content-threshold` option.