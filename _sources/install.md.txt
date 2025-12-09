# {octicon}`download` Installation

```{sidebar}
[![Packaging status](https://repology.org/badge/vertical-allrepos/mail-deduplicate.svg)](https://repology.org/project/mail-deduplicate/versions)
```

Mail Deduplicate is [distributed on PyPi](https://pypi.org/project/mail-deduplicate/).

So you can install the latest stable release with your favorite package manager [like `pip`](https://pip.pypa.io):

```{code-block} shell-session
$ pip install mail-deduplicate
```

## Try it now

You can try Mail Deduplicate right now in your terminal, without installing any dependency or virtual env [thanks to `uvx`](https://docs.astral.sh/uv/guides/tools/):

`````{tab-set}
````{tab-item} Latest version
```shell-session
$ uvx --from mail-deduplicate -- mdedup
```
````

````{tab-item} Specific version
```shell-session
$ uvx --from mail-deduplicate@8.0.0 -- mdedup
```
````

````{tab-item} Development version
```shell-session
$ uvx --from git+https://github.com/kdeldycke/mail-deduplicate -- mdedup
```
````

````{tab-item} Local version
```shell-session
$ uvx --from file:///Users/me/code/mail-deduplicate -- mdedup
```
````
`````

This will download `mail-deduplicate` (the package), and run `mdedup`, the CLI included in the package.

## Installation methods

`````{tab-set}

````{tab-item} uvx
Easiest way is to [install `uv`](https://docs.astral.sh/uv/getting-started/installation/), then install `mail-deduplicate` system-wide, with the [`uv tool`](https://docs.astral.sh/uv/guides/tools/#installing-tools) command:

```{code-block} shell-session
$ uv tool install mail-deduplicate
```

Then you can run `mdedup` directly:

```{code-block} shell-session
$ mdedup --version
```
````

````{tab-item} pipx
[`pipx`](https://pipx.pypa.io/stable/installation/) is a great way to install Python applications globally:

```{code-block} shell-session
$ pipx install mail-deduplicate
```
````

````{tab-item} pip
You can install the latest stable release and its dependencies with a simple `pip` call:

```{code-block} shell-session
$ python -m pip install mail-deduplicate
```

Other variations includes:

```{code-block} shell-session
$ pip install mail-deduplicate
```

```{code-block} shell-session
$ pip3 install mail-deduplicate
```

If you have difficulties to use `pip`, see
[`pip`'s own installation instructions](https://pip.pypa.io/en/stable/installation/).
````

````{tab-item} brew
Mail Deduplicate is [available as an Homebrew formula](https://formulae.brew.sh/formula/mail-deduplicate), so you just need to:

```{code-block} shell-session
$ brew install mail-deduplicate
```
````

````{tab-item} Arch Linux
An `mdedup` package is [available on AUR](https://aur.archlinux.org/packages/mail-deduplicate) and can be installed with any AUR helper:

```{code-block} shell-session
$ pacaur -S mail-deduplicate
```

```{code-block} shell-session
$ pacman -S mail-deduplicate
```

```{code-block} shell-session
$ paru -S mail-deduplicate
```

```{code-block} shell-session
$ yay -S mail-deduplicate
```
````
`````

## Binaries

Binaries are compiled at each release, so you can skip the installation process above and download the standalone executables directly.

This is the preferred way of testing `mdedup` without polluting your machine. They also offer the possibility of running the CLI on older systems not supporting the minimal Python version required by `mdedup`.

| Platform    | `arm64`                                                                                                                                | `x86_64`                                                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **Linux**   | [Download `mdedup-linux-arm64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-linux-arm64.bin)     | [Download `mdedup-linux-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-linux-x64.bin)     |
| **macOS**   | [Download `mdedup-macos-arm64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-arm64.bin)     | [Download `mdedup-macos-x64.bin`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-macos-x64.bin)     |
| **Windows** | [Download `mdedup-windows-arm64.exe`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-windows-arm64.exe) | [Download `mdedup-windows-x64.exe`](https://github.com/kdeldycke/mail-deduplicate/releases/latest/download/mdedup-windows-x64.exe) |

All links above points to the latest released version of `mdedup`.

```{seealso} Older releases
If you need to test previous versions for regression, compatibility or general troubleshooting, you'll find the old binaries attached as assets to [past releases on GitHub](https://github.com/kdeldycke/mail-deduplicate/releases).
```

```{caution} Development builds
Each commit to the development branch triggers the compilation of binaries. This way you can easily test the bleeding edge version of `mdedup` and report any issue.

Look at the [list of latest binary builds](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/release.yaml?query=branch%3Amain+is%3Asuccess). Then select the latest `Build & release`/`release.yaml` workflow run and download the binary artifact corresponding to your platform and architecture.
```

````{note} ABI targets
```{code-block} shell-session
$ file ./mdedup*
./mdedup-linux-arm64.bin:   ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV), dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, BuildID[sha1]=520bfc6f2bb21f48ad568e46752888236552b26a, for GNU/Linux 3.7.0, stripped
./mdedup-linux-x64.bin:     ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, BuildID[sha1]=56ba24bccfa917e6ce9009223e4e83924f616d46, for GNU/Linux 3.2.0, stripped
./mdedup-macos-arm64.bin:   Mach-O 64-bit executable arm64
./mdedup-macos-x64.bin:     Mach-O 64-bit executable x86_64
./mdedup-windows-arm64.exe: PE32+ executable (console) Aarch64, for MS Windows
./mdedup-windows-x64.exe:   PE32+ executable (console) x86-64, for MS Windows
```
````

## Python module usage

Mail Deduplicate should now be available system-wide:

```shell-session
$ mdedup --version
mdedup, version 7.0.0
(...)
```

If not, you can directly execute the module from Python:

```shell-session
$ python -m mail_deduplicate --version
mdedup, version 7.0.0
(...)
```

## Shell completion

Completion for popular shell [rely on Click feature](https://click.palletsprojects.com/en/stable/shell-completion/).

`````{tab-set}

````{tab-item} Bash
:sync: bash
Add this to ``~/.bashrc``:

```{code-block} bash
eval "$(_MDEDUP_COMPLETE=bash_source mdedup)"
```
````

````{tab-item} Zsh
:sync: zsh
Add this to ``~/.zshrc``:

```{code-block} zsh
eval "$(_MDEDUP_COMPLETE=zsh_source mdedup)"
```
````

````{tab-item} Fish
:sync: fish
Add this to ``~/.config/fish/completions/mdedup.fish``:

```{code-block} zsh
eval (env _MDEDUP_COMPLETE=fish_source mdedup)
```
````

`````

Alternatively, export the generated completion code as a static script to be
executed:

`````{tab-set}

````{tab-item} Bash
:sync: bash
```{code-block} shell-session
$ _MDEDUP_COMPLETE=bash_source mdedup > ~/.mdedup-complete.bash
```

Then source it from ``~/.bashrc``:

```{code-block} bash
. ~/.mdedup-complete.bash
```
````

````{tab-item} Zsh
:sync: zsh
```{code-block} shell-session
$ _MDEDUP_COMPLETE=zsh_source mdedup > ~/.mdedup-complete.zsh
```

Then source it from ``~/.zshrc``:

```{code-block} zsh
. ~/.mdedup.zsh
```
````

````{tab-item} Fish
:sync: fish
```{code-block} fish
_MDEDUP_COMPLETE=fish_source mdedup > ~/.config/fish/completions/mdedup.fish
```
````

`````

## Python dependencies

FYI, here is a graph of Python package dependencies:

```mermaid assets/dependencies.mmd
:align: center
```
