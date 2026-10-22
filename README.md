# tools
Claude Code generic tools (Python 3, no packages). Repo-specific tools live in the repo (CodeGenNew: `Docs/Verification/Tools`; CriticalViewer: `tools/deploy/lightsail`).

| Script | Use |
|---|---|
| `edit_text.py` | Exact-count replace that keeps CRLF. `replace_in_file` for one pair, `replace_many` or `FILE --json EDITS.json` for several (all or nothing). Use instead of a one-off script for a multi-line edit. |
| `run_frontend_tests.py` | Installs (when needed) and runs the tests of a React or Angular app folder; prints the summary. |
| `compare_trees.py` | Two source trees matched by file name (a prefix such as `E_` ignored): same, different, only in A, only in B. Comments, blank lines and line endings do not count. For generated against hand-written code. |
| `run_logged.py` | Runs a long command into a log and ends with `FINISHED exit=N`. Start it with `run_in_background: true` so the harness notifies when it ends; no polling, no subshell `&`. |
| `spec_item.py` | `list`, `show`, `move` (spec to completed, optional new heading) and `append` for the numbered `## N.` items of the CodeGenPossibilities spec files; keeps each file's line endings. |
| `sql_run.py` | One guarded SQL statement against MySQL, PostgreSQL or SQL Server through the engine's own client (found on PATH or in Program Files, or borrowed from a running container with `--via`). Refuses a second statement, `GO` and client commands (exit 2); 10 s connect and 30 s query timeouts (exit 124); stops at 10000 rows; the password only travels in `MYSQL_PWD`, `PGPASSWORD` or `SQLCMDPASSWORD` and is redacted from output; notes a statement that cannot be run twice. `--read-only`, `--allow-multi` (a reviewed seed file), `--dry-run`, `--self-test`. |
| `bedrock_probe.py` | AWS Bedrock without boto3: `whoami` (root, IAM user or role, and the account), `models` and `profiles` (which model ids need an inference profile), `converse "prompt"`. Signs requests itself (SigV4) or uses a Bedrock API key; credentials from the environment, the project's .NET user secrets (`--user-secrets DIR`) or the AWS CLI profile, never printed. Explains the usual errors (Error 002, missing inference profile, IAM, signature, expired key). |

Windows Python: pass `C:/x` paths (`compare_trees.py` and `spec_item.py` also accept Git Bash's `/c/x`). Each script prints its usage when run without arguments.
