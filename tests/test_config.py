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

"""Configuration file loading, validation and export."""

from __future__ import annotations

from mailbox import Maildir
from textwrap import dedent

import pytest

from .conftest import MailFactory


@pytest.fixture()
def make_config(tmp_path):
    """Write a TOML configuration file and return its path as a string."""

    def _make_config(content):
        conf_file = tmp_path.joinpath("mdedup.toml")
        conf_file.write_text(dedent(content), encoding="utf-8")
        return str(conf_file)

    return _make_config


def test_config_file_drives_run(invoke, make_box, make_config):
    """Strategy, action and dry-run picked up from a configuration file."""
    duplicate = MailFactory()
    box_path, _, _ = make_box(Maildir, [duplicate, duplicate])
    conf_path = make_config("""\
        [mdedup]
        strategies = ["select-one"]
        action = "delete-discarded"
        dry_run = true
    """)

    result = invoke("--config", conf_path, box_path)

    assert result.exit_code == 0
    assert "select-one strategy will be applied" in result.stderr
    assert "Perform delete-discarded action" in result.stderr
    assert "DRY RUN: Skip action." in result.stderr


def test_config_kebab_case_keys(invoke, make_box, make_config):
    """Kebab-case keys, the TOML convention matching the CLI flags, are accepted."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    conf_path = make_config("""\
        [mdedup]
        hash-only = true
    """)

    result = invoke("--config", conf_path, box_path)

    assert result.exit_code == 0
    assert "Hash:" in result.stdout


def test_config_unknown_key_rejected(invoke, make_box, make_config):
    """A typo in the configuration file aborts the run instead of being ignored."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    conf_path = make_config("""\
        [mdedup]
        strategyy = ["discard-older"]
    """)

    result = invoke("--config", conf_path, box_path)

    assert result.exit_code == 1
    assert "Unknown configuration key 'strategyy'." in result.stderr


def test_config_mail_sources_blocked(invoke, make_box, make_config):
    """Mail sources are command-line only: a config file cannot point at boxes."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    conf_path = make_config(f"""\
        [mdedup]
        mail_sources = ["{box_path}"]
    """)

    result = invoke("--config", conf_path, box_path)

    assert result.exit_code == 1
    assert (
        "Configuration key 'mail_sources' is not allowed in configuration files."
        in result.stderr
    )


def test_config_constraints_apply(invoke, make_box, make_config):
    """Constraints fire on config-sourced values like on command-line ones."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    conf_path = make_config("""\
        [mdedup]
        strategies = ["select-matching-path"]
    """)

    result = invoke("--config", conf_path, box_path)

    assert result.exit_code == 2
    assert "--regexp is required" in result.stderr


def test_cli_overrides_config(invoke, make_config):
    """Command-line values take precedence over configuration file values."""
    conf_path = make_config("""\
        [mdedup]
        size_threshold = 1024
    """)

    result = invoke(
        "--config",
        conf_path,
        "--size-threshold",
        "2048",
        "--params",
        "--table-format",
        "csv",
    )

    assert result.exit_code == 0
    row = [
        line
        for line in result.stdout.splitlines()
        if line.startswith("mdedup.size_threshold,")
    ]
    assert len(row) == 1
    assert ",'2048',COMMANDLINE" in row[0]


def test_pyproject_autodiscovery(invoke, make_box, monkeypatch, tmp_path):
    """A pyproject.toml with a [tool.mdedup] section is discovered from cwd."""
    box_path, _, _ = make_box(Maildir, [MailFactory()])
    tmp_path.joinpath("pyproject.toml").write_text(
        dedent("""\
            [tool.mdedup]
            hash_only = true
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = invoke(box_path)

    assert result.exit_code == 0
    assert "Hash:" in result.stdout


def test_params_reflects_autodiscovered_config(invoke, monkeypatch, tmp_path):
    """--params shows values sourced from an autodiscovered configuration file."""
    tmp_path.joinpath("pyproject.toml").write_text(
        dedent("""\
            [tool.mdedup]
            size_threshold = 1024
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = invoke("--params", "--table-format", "csv")

    assert result.exit_code == 0
    row = [
        line
        for line in result.stdout.splitlines()
        if line.startswith("mdedup.size_threshold,")
    ]
    assert len(row) == 1
    assert ",1024,DEFAULT_MAP" in row[0]


def test_export_config_toml_roundtrip(invoke, make_config):
    """The TOML export names every configurable option and loads back cleanly.

    Loading the exported file back under strict mode is the round-trip
    guarantee: every key the export emits is recognized by the CLI.
    """
    result = invoke("--export-config", "toml")

    assert result.exit_code == 0
    export = result.stdout
    assert "[mdedup]" in export
    # Multi-value options read as lists, unset options as commented-out keys,
    # and keys use the canonical kebab-case spelling.
    assert "strategies = []" in export
    assert "hash-headers = [" in export
    assert "# input-format =" in export
    assert "# regexp =" in export
    assert "# export =" in export
    # Command-line-only and self-referential parameters are not exported.
    assert "mail_sources" not in export
    assert "config" not in export.replace("export_config", "").replace(
        "validate_config", ""
    )

    conf_path = make_config(export)
    result = invoke("--config", conf_path, "--params", "--table-format", "csv")

    assert result.exit_code == 0
