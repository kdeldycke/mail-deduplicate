# {octicon}`book` Man pages

`mdedup` carries a Unix manual page, generated from the live command while this site builds. So the manual always describes the release it ships beside, and nobody writes it by hand.

The index below is rendered by `click_extra.sphinx` from the `click_extra_manpages` list in `docs/conf.py`. Its entry points at the HTML rendering of the page, which the build produces when `mandoc` (preferred) or `groff` is on `PATH`.

```{click-extra-manpages}
```

The raw `mdedup.1` file sits in the same directory as its HTML rendering. [Reading it in a terminal](install.md#man-pages) covers the other ways to read and install it.
