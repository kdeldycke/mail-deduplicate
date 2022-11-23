# Configuration

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

## Troubleshooting

You can easely debug the way `mdedup` source its configuration with the `--show-params`:

```shell-session
$ mdedup --show-params
<TODO: insert result here>
```