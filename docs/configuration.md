# {octicon}`sliders` Configuration

All `mdedup` options can be set with a configuration file, so recurring setups don't have to be retyped on each run.

Values are resolved following the precedence chain: command line arguments, then environment variables, then the configuration file, then built-in defaults. A configuration file never overrides what you type on the command line.

The only parameter that cannot come from a configuration file is the list of mail sources: boxes to deduplicate are always provided on the command line, so a stale entry in a forgotten configuration file cannot silently point a bare `mdedup` call at real mail boxes.

## File formats and keys

TOML, YAML, JSON and INI files are supported. Keys are the option names in `kebab-case`, the spelling of the CLI flags: `hash-body` sets `--hash-body`. The `snake_case` spelling of the internal parameter ID (`hash_body`), as reported by `--params` and used by the `MDEDUP_*` environment variables, is accepted too.

Repeatable options are written as lists. The `strategies` key holds the ordered `--strategy` chain, and `hash-headers` the ordered `--hash-header` list.

```toml
# My default configuration file.

[mdedup]
verbosity = "DEBUG"
strategies = ["discard-older", "select-one"]
action = "delete-discarded"
hash-headers = ["Date", "From", "To", "Subject", "Message-ID"]
size-threshold = 1024
```

Unrecognized keys are rejected: a run aborts with an error naming the offending key, so a typo cannot silently turn into a different deduplication than the one you configured.

## Location

The configuration file is searched in this order:

1. The location passed to `--config`, which accepts a local path, a glob pattern, or a remote URL.
2. A `pyproject.toml` holding a `[tool.mdedup]` section, looked up from the current directory upward to the nearest VCS root, following the discovery behavior of `uv`, `ruff` and `mypy`.
3. The default configuration folder, whose location depends on the OS (see the [`click-extra` documentation](https://kdeldycke.github.io/click-extra/config.html#default-folder)):

| Platform | Folder                                    |
| :------- | :---------------------------------------- |
| macOS    | `~/Library/Application Support/mdedup/`   |
| Unix     | `~/.config/mdedup/`                       |
| Windows  | `C:\Users\<user>\AppData\Roaming\mdedup\` |

To ignore all configuration files for a run, pass `--no-config`.

## Generate a template

The `--export-config` option renders the current configuration, defaults included, in the format of your choice (`toml`, `yaml`, `json`, ...). Redirect it to a file to bootstrap your own:

```{click:run}
from mail_deduplicate.cli import mdedup
invoke(mdedup, args=["--export-config", "toml"])
```

Options without a value are commented out in the TOML export, as TOML has no null type. Combine the flag with other options or environment variables to capture them in the generated file: `mdedup --strategy discard-older --export-config toml` emits a configuration whose `strategies` chain is already filled in.

## Validate a file

The `--validate-config` option checks a configuration file against the CLI's parameters and exits, reporting every unrecognized key at once:

```shell-session
$ mdedup --validate-config ./mdedup.toml
Configuration file ./mdedup.toml is valid.
```

## Environment variables

Every option also reads from an environment variable named after it, prefixed with `MDEDUP_`: `MDEDUP_VERBOSITY`, `MDEDUP_HASH_BODY`, `MDEDUP_DRY_RUN`, ... Environment variables take precedence over the configuration file, but not over the command line.

## Troubleshooting

The `--params` option prints all CLI parameters with their value and provenance (`COMMANDLINE`, `ENVIRONMENT`, `DEFAULT_MAP` for configuration file values, or `DEFAULT`), configuration file included:

```{click:run}
from mail_deduplicate.cli import mdedup
invoke(mdedup, args=["--table-format", "vertical", "--params"])
```
