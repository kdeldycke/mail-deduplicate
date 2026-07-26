# {octicon}`command-palette` CLI parameters

## Help screen

```{click:run}
from mail_deduplicate.cli import mdedup
result = invoke(mdedup, args=["--help"])

assert result.stdout.startswith(
    "\x1b[94m\x1b[4mUsage:\x1b[0m \x1b[97m\x1b[1mmdedup\x1b[0m "
    "\x1b[36m\x1b[2m\x1b[3m[OPTIONS]\x1b[0m \x1b[36m\x1b[3mMAIL_SOURCE_1 MAIL_SOURCE_2 ...\x1b[0m\n"
)
assert "  [\x1b[35m\x1b[1mselect-all-but-one\x1b[0m|\x1b[35m\x1b[1mdiscard-one\x1b[0m]\n" in result.stdout
assert not result.stderr
assert result.exit_code == 0
```

## Options

```{eval-rst}
.. click:: mail_deduplicate.cli:mdedup
    :prog: mdedup
    :nested: full
```
