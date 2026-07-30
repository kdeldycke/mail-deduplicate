from __future__ import annotations

from pathlib import Path

# The docs build runs only on Python >= 3.14 (uv's dependency-groups.docs floor), where
# tomllib is stdlib; mypy analyzes at the 3.10 project floor, where it is absent.
import tomllib  # type: ignore[import-not-found]

project_path = Path(__file__).parent.parent.resolve()

# Fetch general information about the project from pyproject.toml.
toml_path = project_path / "pyproject.toml"
toml_config = tomllib.loads(toml_path.read_text(encoding="utf-8"))

# Redistribute pyproject.toml config to Sphinx.
project_id = toml_config["project"]["name"]
version = release = toml_config["project"]["version"]
url = toml_config["project"]["urls"]["Homepage"]
author = ", ".join(author["name"] for author in toml_config["project"]["authors"])

# Title-case each word of the project ID.
project = " ".join(word.title() for word in project_id.split("-"))
htmlhelp_basename = project_id

# Addons.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    # Adds a copy button to code blocks.
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxext.opengraph",
    "myst_parser",
    "sphinx.ext.autosectionlabel",
    "sphinx_autodoc_typehints",
    "click_extra.sphinx",
    "sphinxcontrib.mermaid",
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
# XXX Allow ```mermaid``` directive to be used without curly braces (```{mermaid}```), see:
# https://github.com/mgaitan/sphinxcontrib-mermaid/issues/99#issuecomment-2339587001
myst_fence_as_directive = ["mermaid"]

# Generate implicit anchors for headings (down to H6) so same-page `#slug` links in
# included Markdown resolve in the build (like readme.md's `#executables`), matching
# GitHub. Drop to 3 if deeper headings ever collide into duplicate-anchor warnings.
myst_heading_anchors = 6

mermaid_d3_zoom = True

# Emit a roff man page (man/mdedup.1, plus an .html sibling when mandoc or groff is
# on PATH) into the HTML build via click-extra's generator, giving packagers a .1
# artifact to install. Uses the same generator as the `mdedup --man` option.
click_extra_manpages = [
    {
        "script": "mail_deduplicate.cli:mdedup",
        "prog_name": "mdedup",
    },
]

# The click:run directives (and their python: siblings) execute build-time Python,
# so click-extra 8.x gates them behind this opt-in (default off). Pages under docs/
# use {click:run} to render live CLI output, so it must be turned on here.
click_extra_enable_exec_directives = True

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

nitpicky = True

# Only categories with no actionable source fix belong here. Re-audit on every
# Sphinx or extension upgrade: build with each entry removed and drop the ones
# whose warning no longer fires (see the sphinx-docs agent § suppress_warnings
# governance).
suppress_warnings = [
    # `index.md` includes `readme.md`, which starts at `## ` because GitHub
    # supplies the H1 from the repo name. The readme must render correctly on
    # GitHub, so its top heading stays H2 by design.
    "myst.header",
    # `sphinx_autodoc_typehints` cannot resolve click's own forward reference
    # `Context` when it documents the inherited `BadParameter` signature: the
    # name is only defined under `TYPE_CHECKING` in `click.exceptions`. Third-
    # party and cosmetic; our own annotations resolve.
    "sphinx_autodoc_typehints.forward_reference",
    # `click_extra.sphinx` renders the live command help (option groups and the
    # excluded-headers reference) into reST for autodoc. Its definition lists and
    # inline-literal spans trip docutils' strict inline parser even though the
    # rendered HTML is correct. There is no source line to fix: the reST is
    # synthesized by the extension, not written by us.
    "docutils",
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

# Theme config.
html_theme = "furo"
html_title = project
html_logo = "assets/mail-deduplicate-logo-square.png"
html_theme_options = {
    "sidebar_hide_name": True,
    # Activates edit links.
    "source_repository": f"https://github.com/{github_user}/{project_id}",
    "source_branch": "main",
    "source_directory": "docs/",
    "announcement": (
        f"{project} works fine, but is <em>maintained by only one person</em> "
        "😶‍🌫️.<br/>You can help if you "
        "<strong><a class='reference external' "
        f"href='https://github.com/sponsors/{github_user}'>"
        "purchase business support 🤝</a></strong> or "
        "<strong><a class='reference external' "
        f"href='https://github.com/sponsors/{github_user}'>"
        "sponsor the project 🫶</a></strong>."
    ),
}

# Footer content.
html_last_updated_fmt = "%Y-%m-%d"
copyright = f"{author} and contributors"
html_show_sphinx = False
