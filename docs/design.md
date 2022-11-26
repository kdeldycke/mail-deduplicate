# Design

This CLI reads all mails from a variety of mailbox formats (`maildir`,
`mbox`, `babyl`, `mh` and `mmdf`), then automatically detects, regroup and
act on duplicates.

Duplicate detection is done by cherry-picking certain headers, in some
cases doing some minor tweaking of the values to reduce them to a
canonical form, and then computing a hash of those headers concatenated
together.

## Hashing headers

In theory, we could rely on the mail's `Message-ID` as a key to identify duplicate mails.

The reality is messier. There is no guarantee that `Message-ID` is unique
or even present. Yes, certain broken mail servers which must remain
nameless are guilty of this. 😩

That is why `mdedup` propose to identify uniqueness of mails based on an ordered hashed list of
headers.

The list of headers to consider can be set with the `-h`/`--hash-header` option.

## Mailing lists

The default parameters of the CLI, especially the [list of default headers](https://kdeldycke.github.io/mail-deduplicate/mail_deduplicate.html#mail_deduplicate.HASH_HEADERS)
have been crafted to limit the effects
of mailing-lists on both the mail headers and body.

Mailing lists effects includes:
- having an extra footer in the mail's body, thus changing the `Content-Length`
  header;
- mails with a new path described by the `Received` headers which would not
  be contained in any copy of the mail saved locally at the time it was
  sent to the list;
- munging the `Reply-To` header even though it's a bad idea;
- adding plenty of other random headers which a copy saved locally at
  sending-time would not have, such as `X-Mailman-Version`,
  `Precedence`, `X-BeenThere`, `List-*`, `Sender`, `Errors-To`, and so
  on;
- adding a prefix to the `Subject` header.


For added protection against accidentally removing mails due to false
positives, duplicates are verified by comparing body sizes and also
diff'ing the contents. If the sizes or contents differ by more than a
threshold, they are not counted as duplicates.
