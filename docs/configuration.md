# {octicon}`sliders` Configuration

All `mdedup` options can be set with a configuration file.

## Location

Location depends on OS (see
[`click-extra` doc](https://kdeldycke.github.io/click-extra/config.html#pattern-matching)):

- macOS:
  `~/Library/Application Support/mdedup/*.{toml,yaml,yml,json,ini,xml}`
- Unix:
  `~/.config/mdedup/*.{toml,yaml,yml,json,ini,xml}`
- Windows (roaming):
  `C:\Users\<user>\AppData\Roaming\mdedup\*.{toml,yaml,yml,json,ini,xml}`

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

```{eval-rst}
.. click:run::
    from mail_deduplicate.cli import mdedup
    invoke(mdedup, args=["--show-params"])
```
