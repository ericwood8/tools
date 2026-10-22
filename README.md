# tools
Claude Code generic tools (Python 3, no packages). Repo-specific tools live in the repo (CodeGenNew: `Docs/Verification/Tools`).

| Script | Use |
|---|---|
| `edit_text.py` | Exact-count replace that keeps CRLF. `replace_in_file` for one pair, `replace_many` or `FILE --json EDITS.json` for several (all or nothing). Use instead of a one-off script for a multi-line edit. |
| `run_frontend_tests.py` | Installs (when needed) and runs the tests of a React or Angular app folder; prints the summary. |
| `compare_trees.py` | Two source trees matched by file name (a prefix such as `E_` ignored): same, different, only in A, only in B. Comments, blank lines and line endings do not count. For generated against hand-written code. |
| `run_logged.py` | Runs a long command into a log and ends with `FINISHED exit=N`. Start it with `run_in_background: true` so the harness notifies when it ends; no polling, no subshell `&`. |
| `spec_item.py` | `list`, `show`, `move` (spec to completed, optional new heading) and `append` for the numbered `## N.` items of the CodeGenPossibilities spec files; keeps each file's line endings. |

Windows Python: pass `C:/x` paths (`compare_trees.py` and `spec_item.py` also accept Git Bash's `/c/x`). Each script prints its usage when run without arguments.
