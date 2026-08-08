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

from mail_deduplicate import deduplicate
from mail_deduplicate.deduplicate import Deduplicate
from mail_deduplicate.mail_box import BoxFormat, BoxStructure

from .conftest import MailFactory

DEDUP_ARGS = ("--strategy=select-newest", "--action=delete-discarded", "--dry-run")

RETAINED_BYTES_CEILING = 2000
"""Upper bound on the bytes the hash index keeps per mail, once hashing is done.

Deliberately loose. A mail stub is mostly its instance dictionary, whose size depends
on the interpreter: the same corpus measures 630 to 675 bytes per mail here on Python
3.14, around 1,100 on 3.10, and has been seen at 1,343 on a CI runner of the very
version that gives 675 locally. A ceiling tight enough to pin any of those is a
ceiling that fails somewhere else.

So this only catches a stub that grew by an order of magnitude, which is what
retaining parsed messages would do. The exact guards on what a stub may carry are
`test_retained_mails_carry_neither_path_nor_payload`, which names the attributes, and
`test_retained_memory_stays_flat_as_the_corpus_grows`, which compares the same
interpreter against itself.
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


def test_retained_memory_stays_flat_as_the_corpus_grows(
    invoke, make_box, index_footprint
):
    """What the index keeps per mail must not grow with the number of mails.

    Measured against itself on one interpreter, so it holds wherever it runs: a
    per-mail figure that climbs with the corpus means something is accumulating that
    should not be. The fixed costs amortize as the corpus grows, so the larger one is
    allowed to come out slightly lower, never higher.
    """
    measured = {}
    for mail_count in (20, 60):
        mails = [
            MailFactory(message_id=f"<m{mail_count}-{i}@nohost.com>")
            for i in range(mail_count)
        ]
        box_path, _, _ = make_box(Maildir, mails)
        assert invoke(*DEDUP_ARGS, box_path).exit_code == 0
        measured[mail_count] = index_footprint["per_mail"]

    assert measured[60] <= measured[20] * 1.05
    assert measured[20] < RETAINED_BYTES_CEILING


def test_retained_memory_does_not_track_mail_size(invoke, make_box, index_footprint):
    """Mails are dehydrated once hashed, so a corpus of huge mails must retain no
    more than a corpus of small ones.

    Regression test for the out-of-memory reports on big boxes: mails used to be
    kept fully parsed for the whole run.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/761
    """
    fat = [
        MailFactory(body="x" * 50_000, message_id=f"<f{i}@nohost.com>")
        for i in range(20)
    ]
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


@pytest.mark.parametrize("box_format", tuple(BoxFormat), ids=str)
def test_parallel_hashing_only_claims_folder_boxes(make_box, config, box_format):
    """Only boxes whose mails own a file can be handed to worker processes.

    Mails of a file-based box are byte ranges of one file that a single handle seeks
    through, so several processes would be seeking the same descriptor.
    """
    box_path, _, _ = make_box(box_format.base_class, [MailFactory()])
    dedup = Deduplicate(config)
    dedup.conf["input_format"] = box_format
    dedup.add_source(box_path)

    claimed = dedup.parallel_boxes()

    if box_format.structure is BoxStructure.FOLDER:
        assert claimed == list(dedup.sources.values())
    else:
        assert claimed == []
    dedup.close_all()


def test_parallel_hashing_falls_back_when_the_pool_will_not_start(
    invoke, make_box, monkeypatch
):
    """A pool that cannot be started must not cost the run its results.

    Frozen and sandboxed environments can refuse to spawn processes. Hashing then
    happens in this one, which is slower and entirely correct.
    """

    def refuse(*args, **kwargs):
        raise OSError("no processes for you")

    monkeypatch.setattr("mail_deduplicate.deduplicate.ProcessPoolExecutor", refuse)
    mails = [MailFactory(message_id=f"<f{i}@nohost.com>") for i in range(6)]
    box_path, _, _ = make_box(Maildir, mails)

    result = invoke("--jobs=4", *DEDUP_ARGS, box_path)

    assert result.exit_code == 0
    assert "Cannot start 4 hashing processes" in result.stderr
    assert "Hash in this process instead" in result.stderr
    # Every mail was still hashed and grouped.
    assert "6" == next(
        cells[1].strip()
        for line in result.stdout.splitlines()
        if (cells := [c.strip() for c in line.split("│") if c.strip()])
        and len(cells) >= 2
        and cells[0] == "Retained"
    )


def test_selection_falls_back_when_the_pool_will_not_start(
    invoke, make_box, monkeypatch
):
    """Selecting across processes must degrade the same way hashing does."""
    started: list[str] = []
    real_pool = deduplicate.ProcessPoolExecutor

    def refuse_selection(*args, **kwargs):
        # Let the hashing pool through, so only the selection one is denied.
        if kwargs.get("initializer") is deduplicate._init_select_worker:
            started.append("refused")
            raise OSError("no processes for you")
        return real_pool(*args, **kwargs)

    monkeypatch.setattr(deduplicate, "ProcessPoolExecutor", refuse_selection)
    pairs = [MailFactory(message_id=f"<s{i}@nohost.com>") for i in range(3)]
    box_path, _, _ = make_box(Maildir, [mail for mail in pairs for _ in range(2)])

    result = invoke("--jobs=4", *DEDUP_ARGS, box_path)

    assert started == ["refused"]
    assert result.exit_code == 0
    assert "Cannot start 4 selection processes" in result.stderr
    assert "Select in this process instead" in result.stderr
    # The duplicates were still found and acted on.
    assert "6" == next(
        cells[1].strip()
        for line in result.stdout.splitlines()
        if (cells := [c.strip() for c in line.split("│") if c.strip()])
        and len(cells) >= 2
        and cells[0] == "Retained"
    )


def test_single_mail_sets_are_not_handed_to_workers(invoke, make_box, monkeypatch):
    """A set of one is settled without reading anything, so shipping it to a worker
    would cost more than deciding it here."""
    handed: list[int] = []
    original = Deduplicate.adopt_selection

    # Spied on this side of the pool on purpose: the worker function itself has to
    # survive pickling to reach a process, which a test's local closure cannot.
    # Only sets that were handed out come back through here.
    def spy(self, hash_key, mail_set, result):
        handed.append(len(mail_set))
        return original(self, hash_key, mail_set, result)

    monkeypatch.setattr(Deduplicate, "adopt_selection", spy)
    # Two lone mails and one duplicate pair.
    mails = [
        MailFactory(message_id="<lonely-one@nohost.com>"),
        MailFactory(message_id="<lonely-two@nohost.com>"),
        MailFactory(message_id="<paired@nohost.com>"),
        MailFactory(message_id="<paired@nohost.com>"),
    ]
    box_path, _, _ = make_box(Maildir, mails)

    assert invoke("--jobs=2", *DEDUP_ARGS, box_path).exit_code == 0

    # Only the pair travelled; neither lone mail did.
    assert handed == [2]


def test_large_duplicate_sets_do_not_diff_every_pair(invoke, make_box, monkeypatch):
    """The cost of a duplicate set must not grow with the square of its size.

    Regression test: the thresholds were confirmed pair by pair, diffing bodies each
    time, so a set of 200 copies of one mail ran 19,900 diffs and took longer than
    20,000 mails arranged in pairs. Mails carrying the same body are now compared
    once between them, and the thresholds are settled over the whole set first.
    See: https://github.com/kdeldycke/mail-deduplicate/issues/87
    """
    diffed: list[int] = []
    original = deduplicate.DuplicateSet.diff

    def spy(self, mail_a, mail_b):
        diffed.append(1)
        return original(self, mail_a, mail_b)

    monkeypatch.setattr(deduplicate.DuplicateSet, "diff", spy)
    # One set of identical copies, the shape that used to blow up.
    copies = [MailFactory(message_id="<swarm@nohost.com>") for _ in range(40)]
    box_path, _, _ = make_box(Maildir, copies)

    assert invoke(*DEDUP_ARGS, box_path).exit_code == 0

    # 40 identical copies would have been 780 pairs to diff. They share one body,
    # so there is nothing to compare at all.
    assert diffed == []


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
