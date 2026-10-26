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

from __future__ import annotations

import logging
import re
import sys
from base64 import b64encode
from collections import Counter
from fractions import Fraction
from importlib.metadata import metadata
from mailbox import Maildir, mbox

import pytest

from mail_deduplicate import bug_report, deduplicate
from mail_deduplicate.bug_report import (
    FAILURE_ATTRIBUTE,
    ISSUES_URL,
    REPORT_END,
    REPORT_START,
    SAMPLES,
    FailureLog,
    blame,
    capture,
    fingerprint,
    render_report,
    report_url,
)
from mail_deduplicate.deduplicate import (
    Deduplicate,
    DuplicateSet,
    MailMeta,
    Stat,
    _hash_in_worker,
    _init_hash_worker,
    _init_select_worker,
    _select_in_worker,
)
from mail_deduplicate.mail import DedupMailMixin
from mail_deduplicate.mail_box import BoxFormat, MaildirDedupMail, resolve_mail_path
from mail_deduplicate.strategy import Strategy

from .conftest import MailFactory, check_box, mail_files, metrics

DOOMED_ID = "<doomed@orchard.example>"
"""`Message-ID` of the test mail that the patched code fails on."""

MAIL_FACTORY_CONTENT = ("foo@bar.com", "A duplicate mail", "Да, они летят.")
"""Header values and body of every `MailFactory` mail, which no report may show."""

PERSONAL = (
    "Clementine Orchard",
    "clementine@orchard.example",
    "quince@orchard.example",
    "Picnic in Lyon",
    "pear-123",
    "Fig-Boundary-77",
    "pommes",
    "plum tart",
    "harvest-plan.pdf",
)
"""Names, addresses and words the test mails spell out, and no fingerprint shows."""

PREAMBLE_MAIL = (
    b"From: Clementine Orchard <clementine@orchard.example>\r\n"
    b"To: quince@orchard.example\r\n"
    b"Subject: Picnic in Lyon\r\n"
    b"Date: Thu, 11 Oct 2018 09:30:00 +0800\r\n"
    b"Message-ID: <pear-123@orchard.example>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="Fig-Boundary-77"\r\n'
    b"\r\n" + "Gâteau aux pommes préparé.\r\n".encode() + b"--Fig-Boundary-77\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Content-Transfer-Encoding: 8bit\r\n"
    b"\r\n"
    b"Bring the plum tart.\r\n"
    b"--Fig-Boundary-77\r\n"
    b'Content-Type: application/pdf; name="harvest-plan.pdf"\r\n'
    b'Content-Disposition: attachment; filename="harvest-plan.pdf"\r\n'
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n" + b64encode(b"%PDF-1.4 apples and pears") + b"\r\n"
    b"--Fig-Boundary-77--\r\n"
)
"""A multipart mail with 8-bit UTF-8 bytes in its preamble, as in
https://github.com/kdeldycke/mail-deduplicate/issues/1085"""

EIGHT_BIT_MAIL = (
    "From: Clementine Orchard <clementine@orchard.example>\n"
    "To: quince@orchard.example\n"
    "Subject: Picnic in Lyon, à midi\n"
    "Date: [mail_date]\n"
    "Message-ID: <pear-123@orchard.example>\n"
    "Content-Type: text/plain; charset=us-ascii\n"
    "\n"
    "Bring the plum tart, à bientôt.\n"
).encode()
"""A mail with 8-bit header values, a body its charset cannot decode and a `Date`
that is no date, as in https://github.com/kdeldycke/mail-deduplicate/issues/954"""


def report_block(output: str) -> str:
    """The lines between the two markers of the bug report in a run's output."""
    start = output.index(REPORT_START)
    return output[start : output.index(REPORT_END, start)]


def fail_on_doomed(monkeypatch, method: str, message: str) -> None:
    """Make a method of the mails raise on the mail carrying `DOOMED_ID`."""
    original = getattr(DedupMailMixin, method)

    def patched(self, *args, **kwargs):
        if self.get("Message-ID") == DOOMED_ID:
            raise RuntimeError(message)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DedupMailMixin, method, patched)


@pytest.fixture()
def worker_state(monkeypatch):
    """Isolate the state a worker function sets up when called in the test process."""
    monkeypatch.setattr(deduplicate, "_WORKER", {})
    root = logging.getLogger()
    level = root.level
    yield
    root.setLevel(level)


@pytest.mark.parametrize("raw", (PREAMBLE_MAIL, EIGHT_BIT_MAIL), ids=("mime", "8bit"))
def test_fingerprint_shows_no_content(raw):
    """A fingerprint never shows a name, an address, a subject, a body or a file
    name, whatever the mail spells out."""
    present = [text for text in PERSONAL if text.encode() in raw]
    # The control: the mail does hold the personal data a leak would show.
    assert len(present) >= 5
    print_ = fingerprint(raw)
    assert [text for text in present if text in print_] == []


def test_fingerprint_shows_mime_structure():
    """The structure of a multipart mail shows, down to the preamble that
    https://github.com/kdeldycke/mail-deduplicate/issues/1085 tripped on."""
    print_ = fingerprint(PREAMBLE_MAIL)
    assert print_.startswith(f"size: {len(PREAMBLE_MAIL)} B, line endings: CRLF\n")
    assert "  Date: 'Thu, 11 Oct 2018 09:30:00 +0800'" in print_
    assert "  MIME-Version: '1.0'" in print_
    assert "  Subject: <14 B ascii>" in print_
    assert "  Content-Type: multipart/mixed; boundary: <17 B ascii>" in print_
    assert re.search(r"multipart/mixed, preamble \d+ B 8-bit UTF-8", print_)
    assert "    text/plain; charset=utf-8, cte 8bit, payload" in print_
    assert re.search(r"application/pdf, cte base64, attachment, .* decoded", print_)


def test_fingerprint_shows_8bit_values():
    """8-bit header values and an undecodable body show by their kind of bytes, and
    a `Date` shows as it is, even when it is no date."""
    print_ = fingerprint(EIGHT_BIT_MAIL)
    assert "line endings: LF" in print_
    assert "  Date: '[mail_date]'" in print_
    assert re.search(r"  Subject: <\d+ B 8-bit UTF-8>", print_)
    assert "text/plain; charset=us-ascii, payload" in print_
    assert "invalid for its charset" in print_


@pytest.mark.parametrize(
    "raw",
    (
        b"",
        b"\x00\xff\xfe",
        b"Subject: \xff\xfe\x00\n\nbody",
        b"a line with no colon\n\nbody",
        b"Content-Type: multipart/mixed; boundary=x\n\n--x\nContent-Type: text/plain\n",
        b"Content-Type: message/rfc822\n\nnot a mail",
        b"Content-Type: text/plain; charset=\xff\xfe\n\nbody",
        b"Subject: a\r\nTo: b\n\nbody\rmore\n",
    ),
)
def test_fingerprint_describes_broken_mails(raw):
    """A broken mail still gets a fingerprint."""
    print_ = fingerprint(raw)
    assert print_.startswith(f"size: {len(raw)} B, line endings: ")


def test_fingerprint_reports_parser_defects():
    """The defects the parser found show on the part they belong to."""
    print_ = fingerprint(
        b"Content-Type: multipart/mixed; boundary=x\n\n--x\nContent-Type: text/plain\n"
    )
    assert "defects CloseBoundaryNotFoundDefect" in print_


def test_fingerprint_counts_mixed_line_endings():
    print_ = fingerprint(b"Subject: a\r\nTo: b\n\nbody\rmore\n")
    assert "line endings: mixed: 1 CRLF, 3 LF, 1 CR" in print_


def test_fingerprint_length_is_capped():
    """A mail with hundreds of headers does not flood the report."""
    raw = b"".join(b"X-Kiwi-%d: %d\n" % (index, index) for index in range(500))
    lines = fingerprint(raw + b"\nbody").splitlines()
    assert len(lines) == bug_report.MAX_FINGERPRINT_LINES + 1
    assert lines[-1].endswith(" more lines")


@pytest.mark.once
def test_issues_url_matches_package_metadata():
    """The URL the report gives is the `Issues` URL of the package."""
    urls = metadata("mail-deduplicate").get_all("Project-URL") or []
    assert f"Issues, {ISSUES_URL}" in urls


def test_traceback_holds_no_path():
    """The traceback of a report names modules and lines, and no file."""
    try:
        raise ValueError("Unexpected melon.")
    except ValueError as expt:
        failure = capture(expt, "hashing")
    assert failure.error == "ValueError: Unexpected melon."
    assert len(failure.frames) == 1
    assert re.fullmatch(
        r"tests\.test_bug_report:\d+ in test_traceback_holds_no_path",
        failure.frames[0],
    )


def test_traceback_starts_in_the_blamed_block():
    """The frame of `blame()` that catches the error stays out of the traceback,
    which names a method with its class from Python 3.11 on."""
    with (
        pytest.raises(ValueError) as exc_info,
        blame(MaildirDedupMail(), "copying"),
    ):
        Fraction("pear")

    frames = getattr(exc_info.value, FAILURE_ATTRIBUTE).frames
    assert re.fullmatch(
        r"tests\.test_bug_report:\d+ in test_traceback_starts_in_the_blamed_block",
        frames[0],
    )
    method = "Fraction.__new__" if sys.version_info >= (3, 11) else "__new__"
    assert re.fullmatch(rf"fractions:\d+ in {re.escape(method)}", frames[-1])


def test_failure_log_keeps_a_few_samples():
    """Every failure is counted, but only the first ones of a kind are kept, with
    their traceback."""
    log = FailureLog()
    failures = []
    for _ in range(5):
        try:
            raise RuntimeError("Unexpected kiwi.")
        except RuntimeError as expt:
            failure = log.capture(expt, "hashing")
        log.add(failure)
        failures.append(failure)

    assert log.counts == Counter({failures[0].kind: 5})
    assert log.samples[failures[0].kind] == failures[:SAMPLES]
    assert all(failure.trace for failure in failures[:SAMPLES])
    assert not any(failure.trace for failure in failures[SAMPLES:])
    assert log.headline() == (
        "mdedup set aside 5 mails after unexpected errors, and acted on none of "
        "their mails."
    )
    assert log.title() == "RuntimeError while hashing"
    assert len(list(log.traces())) == SAMPLES
    lines = list(log.report_lines())
    assert "Failure 1 of 1, while hashing: 5 mails" in lines
    assert "RuntimeError: Unexpected kiwi." in lines


@pytest.mark.parametrize("agent", (True, False))
def test_agents_ask_their_user_first(monkeypatch, agent):
    """An AI agent is asked to show the report to its user before filing it."""
    monkeypatch.setattr(bug_report, "is_any_agent", lambda: agent)
    report = render_report("Headline.", "Title.", ("Detail.",), Counter({"mbox": 2}))
    assert ("AI agent: show this report to your user" in report) is agent
    assert f"\n{ISSUES_URL}/new?template=bug-report.yml&title=Title.\n" in report
    block = report_block(report)
    assert "Sources: 2 mbox" in block
    assert "Options: unknown" in block
    assert "Detail." in block


@pytest.mark.parametrize("box_format", BoxFormat, ids=str)
def test_hashing_error_sets_the_mail_aside(invoke, make_box, monkeypatch, box_format):
    """A mail that fails hashing is set aside and left untouched, the others are
    deduplicated, and the run ends with a bug report."""
    box_type = box_format.base_class
    dup = MailFactory(message_id="<plum@orchard.example>")
    doomed = MailFactory(message_id=DOOMED_ID)
    box_path, _, _ = make_box(box_type, [dup, dup, doomed])
    fail_on_doomed(monkeypatch, "hash_key", "Unexpected tomato.")

    result = invoke(
        f"--input-format={box_format}",
        "--strategy=select-one",
        "--action=delete-discarded",
        box_path,
    )

    assert result.exit_code == 1
    assert "Set aside <" in result.stderr
    assert (
        "after an unexpected error: RuntimeError: Unexpected tomato." in result.stderr
    )
    found = metrics(result.stdout)
    assert found["Failed"] == "1"
    assert found["Retained"] == "2"
    assert "Metrics appear inconsistent" not in result.stderr
    # One copy of the duplicate is deleted, and the failed mail is left alone.
    check_box(box_path, box_type, content=[dup, doomed])

    assert report_url("RuntimeError while hashing") in result.stderr
    block = report_block(result.stderr)
    assert f"Failure 1 of 1, while hashing: 1 mail ({box_format})" in block
    assert "RuntimeError: Unexpected tomato." in block
    assert "Fingerprint of a mail involved:" in block
    # Neither the paths nor the content of the mails reach the block.
    assert box_path not in block
    assert [text for text in MAIL_FACTORY_CONTENT if text in block] == []


def test_hash_only_reports_failures(invoke, make_box, monkeypatch):
    """`--hash-only` prints the hashes it computed, then reports the failed mails."""
    box_path, _, _ = make_box(
        Maildir, [MailFactory(), MailFactory(message_id=DOOMED_ID)]
    )
    fail_on_doomed(monkeypatch, "hash_key", "Unexpected tomato.")

    result = invoke("--hash-only", box_path)

    assert result.exit_code == 1
    assert result.stdout.count("Hash: ") == 1
    assert "while hashing: 1 mail" in report_block(result.stderr)


def test_debug_log_holds_traceback_of_samples(invoke, make_box, monkeypatch):
    """At the debug level, the log holds the full traceback of each failure the
    report details."""
    box_path, _, _ = make_box(Maildir, [MailFactory(message_id=DOOMED_ID)])
    fail_on_doomed(monkeypatch, "hash_key", "Unexpected tomato.")

    result = invoke("--verbosity=DEBUG", "--hash-only", box_path)

    assert result.exit_code == 1
    assert "Traceback of a failure the report details:" in result.stderr
    assert "raise RuntimeError(message)" in result.stderr


def test_report_masks_paths_and_regexps(invoke, make_box, monkeypatch):
    """The options of a report show the values that drive the run, and replace the
    paths and regular expressions, which can name folders and people."""
    dup = MailFactory(message_id="<plum@orchard.example>")
    box_path, _, _ = make_box(Maildir, [dup, dup, MailFactory(message_id=DOOMED_ID)])
    fail_on_doomed(monkeypatch, "hash_key", "Unexpected tomato.")

    result = invoke(
        "--size-threshold=0",
        "--strategy=select-matching-path",
        "--regexp=Orchard[0-9]+",
        "--action=delete-discarded",
        "--dry-run",
        box_path,
    )

    assert result.exit_code == 1
    block = report_block(result.stderr)
    options = next(line for line in block.splitlines() if line.startswith("Options:"))
    assert "--size-threshold 0" in options
    assert "--strategy select-matching-path" in options
    assert "--regexp <regexp>" in options
    assert "--action delete-discarded" in options
    assert "--dry-run" in options
    assert options.endswith(" <path>")
    assert "Orchard" not in block
    assert "Sources: 1 maildir" in block


@pytest.mark.parametrize("box_type", (Maildir, mbox), ids=lambda t: t.__name__)
def test_selection_error_skips_the_set(invoke, make_box, monkeypatch, box_type):
    """A duplicate set that fails selection is skipped, and none of its mails is
    acted upon."""
    dup = MailFactory(message_id="<plum@orchard.example>")
    unique = MailFactory(message_id="<apricot@orchard.example>")
    box_path, _, _ = make_box(box_type, [dup, dup, unique])
    original = DuplicateSet.select

    def select(self):
        if self.size > 1:
            raise RuntimeError("Unexpected pear.")
        return original(self)

    monkeypatch.setattr(DuplicateSet, "select", select)

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 1
    assert "Skip set: unexpected error RuntimeError: Unexpected pear." in result.stderr
    found = metrics(result.stdout)
    assert found["Skipped - Error"] == "1"
    assert found["Deleted"] == "0"
    assert "Metrics appear inconsistent" not in result.stderr
    check_box(box_path, box_type, content=[dup, dup, unique])

    block = report_block(result.stderr)
    assert "Failure 1 of 1, while selecting: 1 set of duplicates" in block
    # The set does not tell which of its mails raised the error: both get described.
    assert block.count("Fingerprint of a mail involved:") == 2


@pytest.mark.parametrize(
    ("action", "patched", "step"),
    (
        ("copy-selected", "mailbox.mbox.add", "copying"),
        ("move-discarded", "mailbox.Maildir.remove", "moving"),
        ("delete-discarded", "mailbox.Maildir.remove", "deleting"),
        ("hardlink-discarded", "filecmp.cmp", "hardlinking"),
    ),
)
def test_action_error_names_its_mail(
    invoke, make_box, monkeypatch, tmp_path, action, patched, step
):
    """An unexpected error in an action stops the run, with a bug report naming and
    describing the mail the action was working on."""
    dup = MailFactory(message_id="<plum@orchard.example>")
    box_path, _, _ = make_box(Maildir, [dup, dup])

    def fail(*args, **kwargs):
        raise RuntimeError("Unexpected fig.")

    monkeypatch.setattr(patched, fail)
    args = ["--strategy=select-one", f"--action={action}", box_path]
    if action.startswith(("copy", "move")):
        args.append(f"--export={tmp_path / 'export.mbox'}")

    result = invoke(*args)

    assert result.exit_code == 1
    assert f"Unexpected error while {step} <MaildirDedupMail " in result.stderr
    assert "Traceback (most recent call last):" in result.stderr
    assert report_url(f"RuntimeError while {step}") in result.stderr
    block = report_block(result.stderr)
    assert f"Failure while {step} (maildir)" in block
    assert "RuntimeError: Unexpected fig." in block
    assert "mail_deduplicate.bug_report:" not in block
    assert "Fingerprint of a mail involved:" in block
    assert box_path not in block
    assert [text for text in MAIL_FACTORY_CONTENT if text in block] == []


def test_action_system_error_is_one_line(invoke, make_box, monkeypatch):
    """An `OSError` in an action is a problem of the system, which the user can fix:
    the run ends with a one-line error naming the mail, and no bug report."""
    dup = MailFactory(message_id="<plum@orchard.example>")
    box_path, box_type, _ = make_box(Maildir, [dup, dup])

    def remove(self, key):
        raise PermissionError(13, "Permission denied", "/pantry/jam")

    monkeypatch.setattr(Maildir, "remove", remove)

    result = invoke("--strategy=select-one", "--action=delete-discarded", box_path)

    assert result.exit_code == 1
    assert (
        "Error: [Errno 13] Permission denied: '/pantry/jam' (while deleting "
        "<MaildirDedupMail " in result.stderr
    )
    assert "Traceback" not in result.stderr
    assert REPORT_START not in result.stderr
    check_box(box_path, box_type, content=[dup, dup])


@pytest.mark.parametrize("failing", ("parse", "hash"))
def test_hashing_worker_returns_its_failure(
    config, make_box, monkeypatch, worker_state, failing
):
    """A worker process sends its failure back as strings: one mail failing does not
    take the pool down with it."""
    box_path, _, _ = make_box(Maildir, [MailFactory(message_id=DOOMED_ID)])
    box = BoxFormat.MAILDIR.constructor(box_path, create=False)
    mail_id = next(iter(box.keys()))
    path = resolve_mail_path(box, mail_id)
    if failing == "parse":

        def load(*args):
            raise RuntimeError("Unexpected tomato.")

        monkeypatch.setattr(deduplicate, "_load_worker_mail", load)
    else:
        fail_on_doomed(monkeypatch, "hash_key", "Unexpected tomato.")

    _init_hash_worker(config, MaildirDedupMail)
    result = _hash_in_worker((box._path, mail_id, path))

    assert (result.mail_hash, result.rejection) == (None, None)
    failure = result.failure
    assert failure is not None
    assert failure.step == "hashing"
    assert failure.error == "RuntimeError: Unexpected tomato."
    assert failure.culprits == (f"<MaildirDedupMail {path}>",)
    assert failure.formats == ("maildir",)
    assert failure.fingerprints[0].startswith("size: ")

    # The parent turns the answer into a stub, set aside with its failure.
    outcome = Deduplicate(config).adopt_hashed(box, mail_id, result)
    assert (outcome.mail_hash, outcome.rejection, outcome.failure) == (
        None,
        None,
        failure,
    )


@pytest.mark.parametrize("failing", ("select", "read"))
def test_selection_worker_skips_its_set(
    config, make_box, monkeypatch, worker_state, failing
):
    """A worker skips a set it cannot settle, and accounts for all of its mails."""
    dup = MailFactory(message_id="<plum@orchard.example>")
    box_path, _, _ = make_box(Maildir, [dup, dup])
    box = BoxFormat.MAILDIR.constructor(box_path, create=False)
    metas = tuple(
        MailMeta(box._path, key, resolve_mail_path(box, key), None, None)
        for key in sorted(box.keys())
    )
    if failing == "read":
        mail_files(box_path)[0].unlink()
    else:

        def select(self):
            raise RuntimeError("Unexpected pear.")

        monkeypatch.setattr(DuplicateSet, "select", select)
    config["strategies"] = (Strategy.SELECT_ONE,)

    _init_select_worker(config, MaildirDedupMail, logging.WARNING)
    result = _select_in_worker(("a-hash", metas))

    assert result.stats == {
        Stat.MAIL_DUPLICATES: 2,
        Stat.MAIL_SKIPPED: 2,
        Stat.SET_SKIPPED_ERROR: 1,
    }
    assert result.selected == result.unique == result.discarded == ()
    messages = [message for _, message in result.records]
    if failing == "read":
        # A file gone is no bug: the set is skipped, with no report.
        assert result.failure is None
        assert any("cannot read its mails again" in m for m in messages)
    else:
        assert result.failure is not None
        assert result.failure.step == "selecting"
        assert len(result.failure.fingerprints) == 2
        assert any(
            "unexpected error RuntimeError: Unexpected pear." in m for m in messages
        )


def test_statistics_self_check_reports_a_bug(config, caplog):
    """Statistics that do not add up end the run with exit code 115 and a bug
    report."""
    dedup = Deduplicate(config)
    dedup.stats[Stat.MAIL_FOUND] = 3
    dedup.stats[Stat.MAIL_RETAINED] = 5

    with pytest.raises(SystemExit) as exc:
        dedup.assert_stats(Stat.MAIL_FOUND, ">=", Stat.MAIL_RETAINED)

    assert exc.value.code == 115
    assert (
        report_url("Statistics do not add up: mail_found >= mail_retained")
        in caplog.text
    )
    block = report_block(caplog.text)
    assert "Failed check: mail_found >= mail_retained, 3 >= 5" in block
    assert "Statistics: mail_found=3, mail_retained=5" in block
