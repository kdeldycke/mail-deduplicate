# CLI parameters


## Help screen

```{eval-rst}
.. click:run::
    from mail_deduplicate.cli import mdedup
    invoke(mdedup, args=["--help"])
```

## Options

```{eval-rst}
.. click:: mail_deduplicate.cli:mdedup
    :prog: mdedup
    :nested: full
```