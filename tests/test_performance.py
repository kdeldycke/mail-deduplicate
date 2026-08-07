# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""Guards against performance regressions.

Wall-clock timings are too noisy to assert on in CI, so these pin the quantities that
actually drive them and are deterministic: how much work a run does per mail, and how
much memory it keeps per mail. The figures documented in `docs/performance.md` and the
readme are derived from the same properties, at a scale no test suite should run.
"""

from __future__ import annotations

import sys
from mailbox import Maildir, mbox

import pytest

from mail_deduplicate.deduplicate import Deduplicate

from .conftest import MailFactory

DEDUP_ARGS = ("--strategy=select-newest", "--action=delete-discarded", "--dry-run")

RETAINED_BYTES_CEILING = 800
"""Upper bound on the bytes the hash index keeps per mail, once hashing is done.

Measured between 630 and 675 bytes on the corpora below, and around 580 on a large
one, where the fixed costs amortize better. The ceiling leaves room for object layouts
to differ between interpreters, while staying under the ~1,000 bytes these same
corpora retained before mails stopped storing their own path, started being grouped in
lists, and began sharing one empty tuple of parsing defects.
See: https://github.com/kdeldycke/mail-deduplicate/issues/87
"""


def deep_size(obj, seen: set[int] | None = None) -> int:
    """Recursive size of an object graph, counting each object once.

    Follows the containers the hash index is made of, and the instance dictionary of
    the mail stubs it holds. Shared references, like the box and the configuration
    every mail points at, are naturally counted a single time.
    """
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0
    seen.add(id(obj))

    total = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            total += deep_size(key, seen) + deep_size(value, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            total += deep_size(item, seen)
    elif hasattr(obj, "__dict__"):
        total += deep_size(vars(obj), seen)
    return total


@pytest.fixture()
def index_footprint(monkeypatch):
    """Captures what the hash index retains, right after hashing."""
    measured: dict[str, object] = {}
    original = Deduplicate.build_sets

    def spy(self):
        mails = [mail for group in self.mails.values() for mail in group]
        # The box and the configuration are pointed at by every mail. Seeding them as
        # already-seen keeps the whole box and config out of the per-mail figure.
        shared = {id(self.conf), *(id(box) for box in self.sources.values())}
        measured["per_mail"] = deep_size(self.mails, shared) / len(mails)
        measured["stub_attrs"] = frozenset(vars(mails[0]))
        return original(self)

    monkeypatch.setattr(Deduplicate, "build_sets", spy)
    return measured


@pytest.fixture()
def count_hashing_reads(monkeypatch):
    """Counts the mail files opened by the hashing step alone.

    Later steps legitimately re-read mails they need the body of, so only the reads
    performed while hashing are counted.
    """
    opened: list[str] = []
    hashing: list[bool] = []
    original_get_file = Maildir.get_file
    original_hash_all = Deduplicate.hash_all

    def spy_get_file(self, key):
        if hashing:
            opened.append(str(key))
        return original_get_file(self, key)

    def spy_hash_all(self):
        hashing.append(True)
        try:
            return original_hash_all(self)
        finally:
            hashing.clear()

    monkeypatch.setattr(Maildir, "get_file", spy_get_file)
    monkeypatch.setattr(Deduplicate, "hash_all", spy_hash_all)
    return opened


def test_hashing_reads_each_mail_once(invoke, make_box, count_hashing_reads):
    """Hashing must open each mail's file exactly once: the read that parses it.

    Regression test: a mail's path used to be read off a second `box.get_file()`
    handle, costing an extra `open()` and `stat()` on every single mail on top of
    the read that already parsed it. The path now comes from the box's own index.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/87
    """
    mail_count = 10
    mails = [MailFactory(message_id=f"<r{i}@nohost.com>") for i in range(mail_count)]
    box_path, _, _ = make_box(Maildir, mails)

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    assert len(count_hashing_reads) == mail_count
    # Each mail is read once, so no mail is read twice.
    assert len(set(count_hashing_reads)) == mail_count


@pytest.mark.parametrize("mail_count", (20, 60))
def test_retained_memory_per_mail_stays_flat(
    invoke, make_box, index_footprint, mail_count
):
    """The hash index must keep a small, constant amount per mail.

    Swept over two corpus sizes: a per-mail figure that grows with the corpus would
    mean something is being retained that should not be.
    """
    mails = [MailFactory(message_id=f"<m{i}@nohost.com>") for i in range(mail_count)]
    box_path, _, _ = make_box(Maildir, mails)

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    assert index_footprint["per_mail"] < RETAINED_BYTES_CEILING


def test_retained_memory_does_not_track_mail_size(invoke, make_box, index_footprint):
    """Mails are dehydrated once hashed, so a corpus of huge mails must retain no
    more than a corpus of small ones.

    Regression test for the out-of-memory reports on big boxes: mails used to be
    kept fully parsed for the whole run.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/761
    """
    fat = [MailFactory(body="x" * 50_000, message_id=f"<f{i}@nohost.com>") for i in range(20)]
    box_path, _, _ = make_box(Maildir, fat)

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    assert index_footprint["per_mail"] < RETAINED_BYTES_CEILING


def test_retained_mails_carry_neither_path_nor_payload(
    invoke, make_box, index_footprint
):
    """A retained mail keeps its identity and its memoized scalars, nothing else.

    Its location is derived from its box on access rather than stored, so burying a
    box under a long path does not inflate every one of its mails. Its parsed
    message is gone entirely, which is what keeps memory flat.
    """
    mails = [MailFactory(message_id=f"<p{i}@nohost.com>") for i in range(20)]
    box_path, _, _ = make_box(Maildir, mails)

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    attrs = index_footprint["stub_attrs"]
    # The mail's own absolute path is derived, never stored.
    assert "path" not in attrs
    # The parsed message is dropped rather than emptied, so a stray read fails loudly.
    assert "_payload" not in attrs
    assert "_headers" not in attrs
    # What the later steps do rely on survives.
    assert {"box", "mail_id", "source_path", "timestamp"} <= attrs


def test_headers_table_is_not_rendered_while_hashing(invoke, make_box, monkeypatch):
    """Rendering a mail's canonical headers goes through `tabulate` and costs more
    than the hash itself, so it must stay out of the hashing path at the default
    verbosity, where its result is discarded.
    """
    from mail_deduplicate.mail import DedupMailMixin

    renders: list[str] = []
    original = DedupMailMixin.pretty_canonical_headers

    def spy(self) -> str:
        rendered = original(self)
        renders.append(rendered)
        return rendered

    monkeypatch.setattr(DedupMailMixin, "pretty_canonical_headers", spy)
    box_path, _, _ = make_box(mbox, [MailFactory() for _ in range(10)])

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    assert renders == []
