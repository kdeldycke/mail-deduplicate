# {octicon}`git-pull-request` Contribution guide

## Development commands

```shell-session
# Run the test suite (test dependencies live in the `test` group).
$ uv run --group test -- pytest

# Run a single test.
$ uv run --group test -- pytest tests/test_strategy.py::test_name

# Type-check at the minimum Python version, with the mypy that the newest
# repomatic release past the cooldown pins. With no target, the runner checks
# what CI checks, `docs/` scripts included.
$ uvx --exclude-newer '1 week' repomatic run mypy

# Build the documentation into the gitignored output directory. Like the CI
# build, it fails on any warning.
$ uv run --group docs -- sphinx-build -b html --fail-on-warning --jobs auto ./docs ./docs/_build/html

# Run the CLI from the working tree.
$ uv run -- mdedup --help
```

## `AGENTS.md` file

```{include} ../AGENTS.md
:start-line: 2
```
