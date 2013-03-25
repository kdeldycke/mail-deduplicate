maildir-deduplicate
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

  * append a footer to a list body, thus changing the Content-Length header

  * create a new path described by the Received headers which would not be contained in any copy of the mail saved locally at the time it was sent to the list

  * munge the Reply-To header even though it's a bad idea

  * add plenty of other random headers which a copy saved locally at sending-time would not have, such as X-Mailman-Version, Precedence, X-BeenThere, List-*, Sender, Errors-To, and so on.

  * add a prefix to the Subject header

Another difficulty is the lack of guarantee that Message-ID is
unique or even present.  Yes, certain broken mail servers which
must remain nameless are guilty of this :-(

For added protection against accidentally removing mails due to
false positives, duplicates are verified by comparing body sizes
and also diff'ing the contents.  If the sizes or contents differ
by more than a threshold, they are not counted as duplicates.

Tested on MacOS X 10.6 with Python 2.6.2 and Linux with Python
2.6.0 and 2.7.2.


Authors
-------

  * Kevin Deldycke <kevin@deldycke.com>
  * Adam Spiers <adam@spiers.net>


License
-------

This code is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, version 2, or any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

For full details, please see the file named COPYING in the top directory of the
source tree. You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
