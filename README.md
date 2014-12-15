Maildir Deduplicate
===================

Command-line tool written in Python to deduplicate mails from a set of maildir folders.


Details
-------

This script reads all mails in a given list of maildir folders and
subfolders, then automatically detects, lists, and optionally
deletes any duplicate mails.

Duplicate detection is done by cherry-picking certain headers, in
some cases doing some minor tweaking of the values to reduce them
to a canonical form, and then computing a digest of those headers
concatenated together.

Note that we deliberately limit this to certain headers due to the
effects that mailing list software can have on not only the mail
header but the body; it can potentially:

  * append a footer to a list body, thus changing the `Content-Length` header

  * create a new path described by the `Received` headers which would not be contained in any copy of the mail saved locally at the time it was sent to the list

  * munge the `Reply-To` header even though it's a bad idea

  * add plenty of other random headers which a copy saved locally at sending-time would not have, such as `X-Mailman-Version`, `Precedence`, `X-BeenThere`, `List-*`, `Sender`, `Errors-To`, and so on.

  * add a prefix to the `Subject` header

Another difficulty is the lack of guarantee that `Message-ID` is
unique or even present.  Yes, certain broken mail servers which
must remain nameless are guilty of this :-(

For added protection against accidentally removing mails due to
false positives, duplicates are verified by comparing body sizes
and also diff'ing the contents.  If the sizes or contents differ
by more than a threshold, they are not counted as duplicates.

So far, it was tested on:

  * MacOS X 10.6 with Python 2.6.2,
  * Linux with Python 2.6.0 and 2.7.2.


Authors & Contributors
----------------------

  * [Kevin Deldycke](https://github.com/kdeldycke)
  * [Adam Spiers](https://github.com/aspiers)
  * [Ben Reser](https://github.com/breser)
  * [Marcel Martin](https://github.com/marcelm)
  * [reedog117](https://github.com/reedog117)
  * [Tristan Henderson](https://github.com/tnhh)
  * [Matija Nalis](https://github.com/mnalis)


History
-------

This script was [initially released in 2010](http://kevin.deldycke.com/2010/08/maildir-deduplication-script-python/), and was living in a [messy GitHub repository](https://github.com/kdeldycke/scripts). After some years, the script basically outgrew its initial intent, and [moved in 2013 to its own repository](http://kevin.deldycke.com/2013/06/maildir-deduplicate-moved/).


License
-------

This software is licensed under the [GNU General Public License v2 or later (GPLv2+)](https://github.com/kdeldycke/maildir-deduplicate/LICENSE.md).
