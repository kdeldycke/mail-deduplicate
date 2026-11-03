from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

TYPE_CHECKING = False
if TYPE_CHECKING:
    from sphinx.application import Sphinx

project_path = Path(__file__).parent.parent.resolve()

# Fetch general information about the project from pyproject.toml.
toml_path = project_path / "pyproject.toml"
toml_config = tomllib.loads(toml_path.read_text(encoding="UTF-8"))

# Redistribute pyproject.toml config to Sphinx.
project_id = toml_config["project"]["name"]
version = release = toml_config["project"]["version"]
author = ", ".join(author["name"] for author in toml_config["project"]["authors"])

# Canonical origin of the published site. The trailing slash is mandatory:
# sphinx-sitemap concatenates it with each page link, and sphinxext-opengraph
# resolves each page with `urljoin`, which drops a last path segment that has no
# trailing slash.
docs_site_url = toml_config["project"]["urls"]["Documentation"].rstrip("/") + "/"

# Title-case each word of the project ID.
project = " ".join(word.title() for word in project_id.split("-"))

# Whole years since `0.0.0` (2010-06-08), the oldest entry of the changelog, for
# the announcement banner below. Floored, so the figure is never ahead of the
# anniversary it claims.
maintained_years = (datetime.now(tz=UTC).date() - date(2010, 6, 8)).days // 365

extensions = [
    # Core Sphinx.
    "sphinx.ext.autodoc",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    # UI/UX add-ons.
    # Adds a copy button to code blocks.
    "sphinx_copybutton",
    "sphinx_design",
    # Emits sitemap.xml from html_baseurl, so crawlers get every page as a list
    # instead of having to discover it by following links.
    "sphinx_sitemap",
    "sphinxext.opengraph",
    # MyST and live CLI rendering.
    "myst_parser",
    # Docstrings are authored in MyST; this extension converts them to reST at
    # build time. It hooks autodoc-process-docstring at priority 400 (vs the
    # default 500) so it always runs before sphinx_autodoc_typehints. Listing it
    # first makes the intent explicit; the extension enforces the order at load
    # time and raises ExtensionError if it is placed after.
    "click_extra.sphinx.myst_docstrings",
    "sphinx_autodoc_typehints",
    "click_extra.sphinx",
    "sphinxcontrib.mermaid",
    # jQuery must be listed explicitly: sphinx-datatables only activates it
    # from a html-page-context callback, too late for the jquery.js static
    # file to be registered and copied, leaving `$` undefined at runtime.
    "sphinxcontrib.jquery",
    "sphinx_datatables",
]

# https://myst-parser.readthedocs.io/en/latest/syntax/optional.html
myst_enable_extensions = [
    # Render GitHub-style alerts (`> [!NOTE]`, `> [!IMPORTANT]`, ...) as
    # admonitions.
    "alert",
    "attrs_block",
    "attrs_inline",
    "deflist",
    "replacements",
    "smartquotes",
    "strikethrough",
    "tasklist",
]
# Allow plain mermaid fences (without curly braces), see
# <https://github.com/mgaitan/sphinxcontrib-mermaid/issues/99#issuecomment-2339587001>.
myst_fence_as_directive = ["mermaid"]

# Generate implicit anchors for headings (down to H6) so same-page `#slug` links in
# included Markdown resolve in the build (like readme.md's `#executables`), matching
# GitHub. Drop to 3 if deeper headings ever collide into duplicate-anchor warnings.
myst_heading_anchors = 6
# Slug the anchors the way docutils builds section IDs, so the two always match.
myst_heading_slug_func = "docutils.nodes.make_id"

# Fail the build on a warning a plain local build would let pass. myst-parser logs
# a `myst.xref_missing` warning for a `#anchor` that matches no heading slug or
# `(target)=` label, and ships the link as written. click-extra logs a
# `click_extra.todo_unrendered` warning for a `{todo}` that no page renders. Sphinx
# exits 0 on warnings, unless the `sphinx.fail-on-warning` setting of the CI build
# adds `--fail-on-warning`.
click_extra_fail_on_warnings = ["click_extra.todo_unrendered", "myst.xref_missing"]

mermaid_d3_zoom = True

# Applies to every table carrying the (default) `sphinx-datatable` class: only the
# binaries catalog. An empty `order` keeps the newest-first rows of the CSV on load,
# instead of DataTables' ascending sort on the first column. The render callback
# adds a relative hint ("9 days ago") to the Released column (index 2) at display
# time only, so sorting and searching keep the raw ISO dates, and the CSV holds no
# hint that goes stale between releases. A raw JS string, because a JSON dict cannot
# carry the function, and raw so the backslashes of the JS regex stay as written.
datatables_options = r"""
{
    "order": [],
    "pageLength": 25,
    "columnDefs": [
        {
            "targets": 2,
            "render": function (data, type, row) {
                if (type !== "display" || !data) {
                    return data;
                }
                // Cells arrive as rendered HTML (<p>2026-07-02</p>), so
                // extract the date instead of parsing the markup.
                const match = /\d{4}-\d{2}-\d{2}/.exec(data);
                if (!match) {
                    return data;
                }
                const days = Math.floor(
                    (Date.now() - Date.parse(match[0])) / 86400000);
                if (!isFinite(days)) {
                    return data;
                }
                let hint;
                if (days <= 0) {
                    hint = "today";
                } else if (days === 1) {
                    hint = "a day ago";
                } else if (days < 30) {
                    hint = days + " days ago";
                } else if (days < 350) {
                    const months = Math.round(days / 30.44);
                    hint = months === 1 ? "a month ago" : months + " months ago";
                } else {
                    const years = Math.round(days / 365.25);
                    hint = years === 1 ? "a year ago" : years + " years ago";
                }
                // Inject inside the paragraph so the hint stays on the
                // same line as the date.
                const label = " (" + hint + ")";
                return data.includes("</p>")
                    ? data.replace("</p>", label + "</p>")
                    : data + label;
            }
        }
    ]
}
"""

# Emit a roff man page (man/mdedup.1, plus an .html sibling when mandoc or groff is
# on PATH) into the HTML build via click-extra's generator, giving packagers a .1
# artifact to install. Uses the same generator as `mdedup --help-format man`.
click_extra_manpages = [
    {
        "script": "mail_deduplicate.cli:mdedup",
        "prog_name": "mdedup",
    },
]

# The click:run directives (and their python: siblings) execute build-time Python,
# so click-extra gates them behind this opt-in (default off). Pages under docs/
# use {click:run} to render live CLI output, so it must be turned on here.
click_extra_enable_exec_directives = True

exclude_patterns = ["_build", "_linkcheck", "html", "Thumbs.db", ".DS_Store"]

nitpicky = True
# `AnyValueIn` subclasses cloup's `Predicate`, and autodoc lists that base class by
# its full path. No inventory is mapped for cloup, so there is nothing to link to:
# stop nitpicky mode asking for it. Click's `ProgressBar`, which `step_progressbar()`
# returns, lives in a private module its documentation never lists.
nitpick_ignore = [
    ("py:class", "click._termui_impl.ProgressBar"),
    ("py:class", "cloup.constraints.conditions.Predicate"),
]

# Only categories with no actionable source fix belong here. Re-audit on every
# Sphinx or extension upgrade: build with each entry removed and drop the ones
# whose warning no longer fires (see the sphinx-docs agent § suppress_warnings
# governance).
suppress_warnings = [
    # `index.md` includes `readme.md`, which starts at `## ` because GitHub
    # supplies the H1 from the repo name. The readme must render correctly on
    # GitHub, so its top heading stays H2 by design.
    "myst.header",
]

# Concatenates the docstrings of the class and the __init__ method.
autoclass_content = "both"
# Keep the same ordering as in original source code.
autodoc_member_order = "bysource"

# If true, `todo` and `todoList` produce output, else they produce nothing.
todo_include_todos = True

github_user = "kdeldycke"

intersphinx_mapping = {
    "click_extra": ("https://kdeldycke.github.io/click-extra", None),
    "python": ("https://docs.python.org/3", None),
}

# Prefix document path to section labels, to use:
# `path/to/file:heading` instead of just `heading`
autosectionlabel_prefix_document = True

# Linkcheck configuration, mirroring the reference one from repomatic.
# GitHub renders issue comments, readme tab anchors and blob line anchors with
# JavaScript, so the linkcheck builder cannot find them in the static HTML.
linkcheck_anchors_ignore = [
    r"issuecomment-\d+",
    r"readme",
    r"L\d+",
]

linkcheck_anchors_ignore_for_url = [
    r"https://github\.com/",
]

# Some links time out the linkcheck bot intermittently; retry before reporting
# them as broken.
linkcheck_retries = 3

linkcheck_ignore = [
    # claude.ai/code requires authentication.
    r"https://claude\.ai/code",
    # isync.sourceforge.io returns 403 to bots but is valid.
    r"https://isync\.sourceforge\.io",
]

# Sphinx emits a `<link rel="canonical">` on every page from this base, and
# sphinx-sitemap builds sitemap.xml from it.
html_baseurl = docs_site_url
# sphinx-sitemap defaults to a `{lang}{version}{link}` layout, for sites that publish
# translations or versions side by side. This site publishes one tree, so anything
# but the bare link yields sitemap entries that 404.
sitemap_url_scheme = "{link}"

# Absolute base of the OpenGraph tags. It reads the same constant as html_baseurl,
# so og:url and the canonical link always name the same page.
ogp_site_url = docs_site_url
# The social card, served by the site itself: sphinxext.opengraph joins it onto
# ogp_site_url, and its html_static_path entry below puts the file under _static/.
ogp_image = "_static/banner-social-light.png"
ogp_image_alt = project

# Theme config.
html_theme = "furo"
html_title = project
# The mark is a raster illustration with no SVG source, so the favicon is its
# transparent PNG icon, the same file the binaries embed.
html_favicon = "assets/icon.png"
html_theme_options = {
    # Furo's logo pair, resolved against _static/. Never html_logo, which Furo
    # prefers to the pair. The logo is transparent and its yellow lettering reads on
    # both themes, so one file serves both.
    "light_logo": "mail-deduplicate-logo-square.png",
    "dark_logo": "mail-deduplicate-logo-square.png",
    "sidebar_hide_name": True,
    # Activates edit links.
    "source_repository": f"https://github.com/{github_user}/{project_id}",
    "source_branch": "main",
    "source_directory": "docs/",
    # Sits atop every page, so it stays a single line and leads with the track
    # record rather than pleading scarcity: how thin the maintenance is says
    # nothing to a reader who has not yet decided the project is worth funding.
    # The age is recomputed at build time, so the claim never goes stale. Each
    # call to action opens on its emoji, which gives the eye two markers to land
    # on in a line that is otherwise unbroken prose.
    "announcement": (
        f"{project} has been maintained for {maintained_years}+ years, and is "
        "free to use. You can help if you "
        "<strong><a class='reference external' "
        f"href='https://github.com/sponsors/{github_user}'>"
        "🤝 purchase business support</a></strong> or "
        "<strong><a class='reference external' "
        f"href='https://github.com/sponsors/{github_user}'>"
        "🫶 sponsor the project</a></strong>."
    ),
}

# Footer content.
html_last_updated_fmt = "%Y-%m-%d"
copyright = f"{author} and contributors"
html_show_sphinx = False

# Do not publish a copy of every source document under `_sources/`: no page links
# to it, and the sources are in the repository. `html_copy_source` gates the files
# and `html_show_sourcelink` the link, so a theme that reads only the second does
# not offer a link to files that are no longer there.
html_copy_source = False
html_show_sourcelink = False

# Copied verbatim to the root of the build, where GitHub Pages looks for a custom
# `404.html`. html_static_path would put it under `_static/` instead.
html_extra_path = ["404.html"]

# Individual files land at the root of _static/, where Furo looks for the logo pair
# and where ogp_image points. Listing docs/assets/ whole would copy every capture.
html_static_path = [
    "_static",
    "assets/banner-social-light.png",
    "assets/mail-deduplicate-logo-square.png",
]
# Hides the readme banner on the front page, where the sidebar already shows the logo.
html_css_files = ["custom.css"]


def prune_build_artifacts(app: Sphinx, exception: Exception | None) -> None:
    """Delete the files Sphinx leaves in the output tree that are not content.

    `.buildinfo` records the configuration hash that an incremental build compares
    against, and `.buildinfo.bak` is the copy Sphinx keeps when that comparison
    fails. No setting suppresses them: the HTML builder always writes `.buildinfo`
    when the build finishes.

    Sphinx also creates `_sources/` whatever `html_copy_source` says, so switching
    that setting off leaves an empty directory. This hook deletes the directory
    only while it is empty.
    """
    if exception:
        return
    outdir = Path(app.outdir)
    for marker in (".buildinfo", ".buildinfo.bak"):
        (outdir / marker).unlink(missing_ok=True)
    sources = outdir / "_sources"
    if sources.is_dir() and not any(sources.iterdir()):
        sources.rmdir()


def setup(app: Sphinx) -> None:
    """Prune the non-content files once the build finishes."""
    app.connect("build-finished", prune_build_artifacts)
