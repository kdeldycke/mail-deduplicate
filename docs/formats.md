# {octicon}`inbox` Box formats

## Supported formats

`mdedup` reads and writes six box formats. Three of them keep each mail in a file of its own, and the other three keep a whole box in one file:

| Format    | Storage           | Lock                     |
| :-------- | :---------------- | :----------------------- |
| `maildir` | One file per mail | None                     |
| `mbox`    | One file per box  | The box file             |
| `mh`      | One file per mail | The `.mh_sequences` file |
| `babyl`   | One file per box  | The box file             |
| `mmdf`    | One file per box  | The box file             |
| `eml`     | One file per mail | None                     |

`--input-format` and `--export-format` take the names of the first column.

## Autodetection

Without `--input-format`, `mdedup` finds the format of each source by itself, so one run can mix sources of different formats. A file takes its format from the bytes it starts with:

- `babyl`, when it starts with `BABYL OPTIONS:`.
- `mmdf`, when it starts with four Control-A characters, which separate its mails.
- `eml`, when it starts with a header: the file holds one mail saved alone, like an `.eml` file.
- `mbox`, in any other case.

A folder takes the first format that fits:

1. `mh`, when the folder holds a `.mh_sequences` file.
2. `maildir`, when the folder holds a `cur` and a `tmp` folder, or holds such a folder at any depth.
3. `eml`, when the folder holds a file whose name ends with `.eml`, at any depth.
4. `mbox`, when the folder holds an [`mbox` file](#mbox-mmdf-and-babyl), at any depth.

A folder that fits none of them stops the run with an error.

The first format that fits applies to the whole folder. A folder that holds `maildir` folders and `.eml` files is read as `maildir` alone, and its `.eml` files are skipped. Give each part as a source of its own.

A folder of numbered mails with no `.mh_sequences` file is not detected as `mh`. Create an empty `.mh_sequences` file in it before the run.

`--input-format` skips the detection and names the format of every source of the run.

A run warns about each source in which it finds no mail.

## `maildir`

A folder is a `maildir` when it holds a `cur` and a `tmp` folder. The `new` folder is optional, as Thunderbird does not create it. A copy made by a tool that skips empty folders, like `git`, can lack `tmp`. `mdedup` then skips that `maildir` with a warning, even with `--input-format maildir`: create an empty `tmp` folder again before the run.

`mdedup` reads the sub-folders of a `maildir` in the two layouts that mail tools use:

- Maildir++, where each sub-folder is a `maildir` inside the top folder, with a name that starts with a `.`.
- The Verbatim layout of [isync/mbsync](https://isync.sourceforge.io/mbsync.html), where each sub-folder is a plain folder, nested at any depth, and a `maildir` of its own.

A folder without `cur` and `tmp` only holds other folders, so `mdedup` reads no mail at its level.

A `maildir` keeps the state of a mail outside of its content. The `new` or `cur` folder tells whether a client saw the mail. The end of the file name holds its flags. The modification time of the file is the time the mail arrived. [Writing to a box](#writing-to-a-box) tells which of these a copy keeps.

## `mbox`, `mmdf` and `babyl`

Each of these formats keeps a whole box in one file.

A folder given as a source can hold `mbox` files at any depth, like the folders of a [Thunderbird](#thunderbird) account. Each of these files is then a box of its own. A file opens as a box when it starts with a `From ` line, or when it has an `.msf` summary beside it, as an empty Thunderbird folder has. In any folder, the walk skips the names that Thunderbird never shows as folders: the ones starting with `.` or `#` or ending with `~`, the `.msf` summaries, and the `.mozmsgs` directories.

`mmdf` and `babyl` boxes have no such folder form: give each of their files as a source.

Each `mbox`, `babyl` and `mmdf` box keeps its file open until the end of the run, so the limit of open files of the system caps how many of them one run holds. macOS sets that limit to 256 by default, which a Thunderbird account of a few hundred folders goes past. The run then stops with a `too many open files` error. Raise the limit in the shell before the run, like with `ulimit -n 4096`, or deduplicate fewer boxes at once.

A run that deletes or moves mails out of such a box rewrites its whole file at the end. The new file is written beside the old one before it replaces it, so the disk needs room for a second copy of the box.

## `eml`

An `eml` source is a folder of mails saved one per file, like the files that conversion tools export from an Outlook PST archive. `mdedup` walks all its sub-folders and reads each file whose name ends with `.eml`, in any case. It skips the files and folders whose name starts with a `.`. A single mail file given as a source is an `eml` box of that one mail, whatever its name.

An `eml` export box keeps each mail in a file of its own, at the top of the folder, with a random name.

## Thunderbird

Thunderbird stores an account in one of two ways, and `mdedup` reads both:

- By default, each folder is one `mbox` file, named after the folder with no extension added. The sub-folders of a folder are in its `<folder>.sbd` directory, and an `.msf` summary of the folder is beside it. `mdedup` reads the account as a [folder of `mbox` files](#mbox-mmdf-and-babyl).
- An account of one file per message is read as `maildir` boxes. Each of its folders is a directory with `cur` and `tmp` sub-directories but no `new`.

A tree that holds accounts of both kinds is read as `maildir` alone: give each account as a source of its own.

```{warning}
Quit Thunderbird before you run `mdedup` on its folders: Thunderbird does not check the locks that `mdedup` takes. When the size or the date of an `mbox` folder file changes, Thunderbird rebuilds the summary of that folder from the file. It does not check a folder of one file per message: after a run that deletes or moves its mails, click Repair Folder in the properties of that folder, or Thunderbird keeps showing the mails that are gone.

Thunderbird locks its profile while it runs, so a run that deletes or moves mails refuses a profile that Thunderbird has open. A copy, a `--dry-run` or a `--hash-only` run goes on. The check does not see an account whose directory is outside the profile, nor a profile on a network file system.

Give `mdedup` the `Mail` directory of the profile, or one of its accounts, like `Mail/Local Folders`. Do not give it the `ImapMail` directory: its `mbox` files are offline copies of the mails on IMAP servers. Thunderbird finds each mail there by its position in the file, and does not check these files against their summaries.
```

## Locks

`mdedup` locks each box when it opens it, and keeps the lock until the end of the run. It locks an `mbox`, `mmdf` or `babyl` box through its file, and an `mh` folder through its `.mh_sequences` file. Each lock also puts a `.lock` file beside the file it locks. A `maildir` or `eml` box needs no lock, as each of its mails has a file of its own.

A box that another program locked stops the run with an error. A program that crashed can leave its `.lock` file behind. If no other program uses the box, run again with `--force-unlock`, which removes that file.

A run that fails, or that you interrupt, unlocks all its boxes, so the next run needs no `--force-unlock`. No `.lock` file then stays in a Thunderbird account, where Thunderbird would show it as a folder.

Such a run also leaves each `mbox`, `mmdf` and `babyl` source as it found it. These formats write a deletion only when a run ends without error, as they rewrite their file then. A mail that the output of a failed run lists as deleted or moved stays in such a box, and a warning names the box. A mail deleted from a `maildir`, `mh` or `eml` box is gone at once.

## Writing to a box

`--export-format` sets the format of the export box, `mbox` by default. A run refuses an export box that already exists, unless `--export-append` adds the mails to it.

The `copy-*` and `move-*` actions write each mail into the export box as the bytes its source box holds, never as a message rebuilt from its parsed form. Python's `email` generator redraws multipart boundaries, closes a boundary left open, turns a bare CR into a line break, and drops the content of a multipart part it parsed with no subpart: a deduplication is no reason to repair a mail. Line endings are the one conversion left. A mail is written with LF endings, which every format but `eml` turns into the line separator of the platform. An `mbox` or `mmdf` box also quotes the body lines starting with `From `, as its format requires. The quote stays in the mail when a run copies it out of that box.

What a format keeps beside a mail travels with it into a box of the same format:

| Kept beside the mail                                           | By             | Travels into   |
| :------------------------------------------------------------- | :------------- | :------------- |
| The envelope `From ` line                                      | `mbox`, `mmdf` | `mbox`, `mmdf` |
| The `new` or `cur` folder, the flags and the modification time | `maildir`      | `maildir`      |
| The sequences, like `unseen`                                   | `mh`           | `mh`           |
| The labels                                                     | `babyl`        | No box         |

Nothing is translated from one format to another. A `maildir` mail copied into an `mbox` gets no `Status` header, and loses its flags. A mail copied into a `maildir` from another format lands in `new`, with no flags, and with the time of the run as its modification time. IMAP servers like Dovecot show that time as the date the mail arrived.

## How the format changes a run

- `--regexp` tests the path of each mail file in a `maildir`, `mh` or `eml` box. Every mail of an `mbox`, `mmdf` or `babyl` box shares the path of the box file. The path of a `maildir` mail ends with its `cur` or `new` folder and its file name, flags included.
- `--time-source mtime` and `--time-source ctime` read a time of the file that holds a mail, so every mail of an `mbox`, `mmdf` or `babyl` box gets the time of its box. `mtime` is the time the content of the file last changed: for a `maildir` mail, the time it arrived. On Linux and macOS, `ctime` is the time of the last change to the metadata of the file, not its creation time: a client that sets a flag on a `maildir` mail renames its file, which changes its `ctime` but not its `mtime`.
- `--jobs` works in parallel only when every source is a `maildir`, `mh` or `eml` box: one `mbox`, `mmdf` or `babyl` source keeps the whole run sequential. See [running in parallel](performance.md#running-in-parallel).
- `--cache` trusts an entry only while the file of its mail is unchanged. For an `mbox`, `mmdf` or `babyl` mail, that file is the whole box. See [what invalidates an entry](performance.md#what-invalidates-an-entry).
- `--action hardlink-discarded` leaves alone the mails of an `mbox`, `mmdf` or `babyl` box, which have no file of their own to link. See [hardlinking duplicates](design.md#hardlinking-duplicates).
