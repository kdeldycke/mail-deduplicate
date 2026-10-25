# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""Allow the module to be run as a CLI. I.e.:

```{code-block} shell-session

$ python -m mail_deduplicate
```
"""

from __future__ import annotations

import builtins
import multiprocessing
import sys

WORKER_RERUN_ERROR = (
    "Refusing to run mdedup inside one of its own worker processes. This "
    "executable starts the CLI again in each --jobs worker. Use --jobs=1 to run "
    "without workers."
)
"""Message a worker exits with when its launcher starts the CLI again in it."""


def in_worker_process() -> bool:
    """Tell whether this process is a `--jobs` worker that has not started its task.

    A launcher without a `__name__ == "__main__"` guard calls {func}`main` again in
    each worker it starts, as the one Nuitka writes for `--main-entry-point` does.
    Two states reveal that call:

    - A spawn or forkserver worker imports the main module of its parent while
      `multiprocessing` sets the `_inheriting` flag of the process. CPython reads
      the same flag, but only refuses once the CLI starts a process, after it
      opened the boxes.
    - A Nuitka worker runs the launcher before any bootstrap, so no flag is set
      yet. Nuitka's multiprocessing plugin first saves the command line of the
      worker as `builtins.__nuitka_original_args`.
    """
    return bool(
        getattr(multiprocessing.current_process(), "_inheriting", False)
        or hasattr(builtins, "__nuitka_original_args")
    )


def main():
    """Execute the CLI.

    Indirection via this `main()` method was [required to reconcile](https://github.com/python-poetry/poetry/issues/5981):

        - plain inline package call: `python -m mail_deduplicate`,
        - `pyproject.toml` entry point: `mdedup = 'mail_deduplicate.__main__:main`,
        - Nuitka's entry point:
          `python -m nuitka (...) --main-entry-point=mdedup=mail_deduplicate.__main__:main`

    That way we can deduce all three cases from the entry point.

    The CLI's display name doesn't need to be forced here: `click-extra`'s
    `Command.main()` already defaults `prog_name` to the command's name, so even
    `python -m mail_deduplicate --version` reports itself as `mdedup`.
    """
    # `--jobs` hashes in worker processes, which a frozen binary starts by launching
    # itself again. When the freezer sets `sys.frozen`, as PyInstaller does, this
    # call turns that launch into the worker and never returns. A no-op elsewhere.
    multiprocessing.freeze_support()

    # Nuitka sets no `sys.frozen`, and its launcher can still call this function in
    # each worker: stop there, before the CLI opens a box or starts more workers.
    if in_worker_process():
        sys.exit(WORKER_RERUN_ERROR)

    from mail_deduplicate.cli import mdedup

    mdedup()


if __name__ == "__main__":
    main()
