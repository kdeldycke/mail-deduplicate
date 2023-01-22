# Installation

`````{tab-set}

````{tab-item} pipx
Easiest way is to [install `pipx`](https://pypa.github.io/pipx/installation/), then use it to install `mdedup`:

```{code-block} shell-session
$ pipx install mail-deduplicate
```

`pipx` is to `pip` what `npx` is to `npm`: a clean way to install and run Python applications in isolated environments.
````

````{tab-item} pip
You can install the latest stable release and its dependencies with a simple `pip`
call:

```{code-block} shell-session
$ python -m pip install mail-deduplicate
```

On some system, due to the Python 2.x to 3.x migration, you'll have to call `python3` directly:

```{code-block} shell-session
$ python3 -m pip install mail-deduplicate
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
`````

## Run `mdedup`

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

Or on some systems:

```shell-session
$ python3 -m mail_deduplicate --version
mdedup, version 7.0.0
(...)
```

## Shell completion

Completion for popular shell
[rely on Click feature](https://click.palletsprojects.com/en/8.1.x/shell-completion/).

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

```{eval-rst}
.. graphviz:: images/dependencies.dot
   :align: center
```