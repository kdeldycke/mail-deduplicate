# {octicon}`sliders` Configuration

All `mdedup` options can be set with a configuration file.

## Location

Location depends on OS (see [`click-extra` doc](https://kdeldycke.github.io/click-extra/config.html#default-folder)):

| Platform          | Folder                                    |
| :---------------- | :---------------------------------------- |
| macOS    | `~/Library/Application Support/mdedup/`   |
| Unix     | `~/.config/mdedup/`                       |
| Windows  | `C:\Users\<user>\AppData\Roaming\mdedup\` |

## TOML sample

```toml
# My default configuration file.

[mdedup]
verbosity = "DEBUG"
strategy = "discard-older"
action = "delete-discarded"
```

## Troubleshooting

You can easily debug the way `mdedup` source its configuration with the `--show-params`:

```{click:run}
from mail_deduplicate.cli import mdedup
invoke(mdedup, args=["--table-format", "vertical", "--show-params"])
```