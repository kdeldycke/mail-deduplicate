---
name: Bug report
about: Create a report to help improve the project
title: ''
labels: 'bug'
assignees: 'kdeldycke'
---

#### Describe the bug

A clear and concise description of what the bug is.

#### To reproduce

Steps to reproduce the behavior:
1. The full `mdedup` CLI invocation you used.
1. The data set leading to the bug.
   Try to produce here the minimal subset of mails leading to the bug, and add copies of those mails (eventually censored).
   This effort will help maintainers add this particular edge-case to the set of unittests to prevent future regressions.
   You can reduce down the issue to a particular deduplicate subset by using the `--hash-only` parameter.

#### Expected behavior

A clear and concise description of what you expected to happen.

#### CLI output

Add here a copy of the console output of:
* The `mdedup` CLI invocation and its output
* The Python traceback you encountered
* The `mdedup` output, but this time the `--verbosity=DEBUG` parameter 

Wisely choose to feature here the full output or excerpt relevant to the bug you're trying to highlight.

#### Environment

- OS: [e.g. macOS 10.14.5, Linux Ubuntu 19.04]
- Python version: i.e. output of `$ python --version`
- Mail deduplicate version: i.e. output of `$ mdedup --version`

#### Additional context

Add any other context about the problem here.
