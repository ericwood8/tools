"""Runs one guarded SQL statement against MySQL, PostgreSQL or SQL Server through the engine's own command line client.

  python sql_run.py --engine mysql --host 127.0.0.1 --user app --db shop -e "SELECT id, title FROM movies"
  python sql_run.py --engine postgres --user dev --db shop --file query.sql
  python sql_run.py --engine mssql --host MYPC --trusted --db Shop -e "SELECT TOP 5 * FROM Customer"
  python sql_run.py --engine mysql --via mysql_dev --host db.example.com --user u --db d -e "SELECT 1"     (borrow a container's client)

Enforced on every run:
  1. one statement: a second statement, a GO line, or a client command (mysql `system`/`source`/`delimiter`, psql `\\!`, sqlcmd `:r`/`!!`)
     is refused with exit code 2 (--allow-multi lifts the statement count for a reviewed seed file; client commands stay refused)
  2. timeouts: 10 s to connect, 30 s per query, and the whole process is killed a few seconds after that
  3. at most 10000 output rows (the client streams; the tool stops reading and kills it, then says so)
  4. the password never appears on a command line or in output: it travels in MYSQL_PWD, PGPASSWORD or SQLCMDPASSWORD, and any
     occurrence of it (and `Password=...`) is replaced with REDACTED in everything printed
  5. idempotence: a statement that cannot be run twice (CREATE TABLE without IF NOT EXISTS, a plain INSERT, DROP without IF EXISTS)
     prints a note on stderr; it is a hint, not a refusal

--password-env NAME reads the password from another environment variable. --trusted is Windows authentication (SQL Server).
--read-only refuses anything but SELECT/SHOW/DESCRIBE/EXPLAIN/WITH (a first word check, not a boundary: use a read-only login for that).
--dry-run prints the redacted command and runs nothing. --self-test checks the statement splitter and the redaction.
Output is tab separated with a header line. Clients: PATH, then Program Files (MySQL, PostgreSQL); sqlcmd must be on PATH.
SQL Server cells are trimmed and cut at 8000 characters (a sqlcmd limit: use bcp for longer text). sqlcmd runs without -X1, which would make
it ignore SQLCMDPASSWORD; the refusal of `:` and `!!` lines is what keeps its scripting commands out.
Exit codes: 0 ok, 2 refused, 124 timeout (killed, or the engine's own timeout message), otherwise the client's.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

CONNECT_TIMEOUT = 10
QUERY_TIMEOUT = 30
KILL_AFTER = CONNECT_TIMEOUT + QUERY_TIMEOUT + 5
ROW_CAP = 10000
EXIT_REFUSED = 2
EXIT_TIMEOUT = 124
TIMEOUT_MESSAGE = {
    "mysql": re.compile(r"maximum statement execution time exceeded"),
    "postgres": re.compile(r"canceling statement due to statement timeout"),
    "mssql": re.compile(r"Timeout expired"),
}

ENGINES = {
    "mysql": {"exe": "mysql", "password_env": "MYSQL_PWD", "container_exe": "mysql"},
    "postgres": {"exe": "psql", "password_env": "PGPASSWORD", "container_exe": "psql"},
    "mssql": {"exe": "sqlcmd", "password_env": "SQLCMDPASSWORD", "container_exe": "/opt/mssql-tools18/bin/sqlcmd"},
}
FALLBACK_GLOBS = {"mysql": ["C:/Program Files/MySQL/*/bin/mysql.exe"], "psql": ["C:/Program Files/PostgreSQL/*/bin/psql.exe"]}

CLIENT_COMMAND = {
    "mysql": re.compile(r"^\s*(\\|(?:system|source|tee|pager|delimiter)\s+\S+\s*;?\s*$)", re.I | re.M),
    "postgres": re.compile(r"^\s*\\", re.M),
    "mssql": re.compile(r"^\s*(:[A-Za-z]|!!)", re.M),
}
GO_LINE = re.compile(r"^\s*GO(\s+\d+)?\s*;?\s*$", re.I | re.M)
READ_ONLY_START = ("select", "show", "describe", "desc", "explain", "with")
DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")


def quoted_end(sql, i, engine):
    """Index just after the quoted text that starts at sql[i] ('...', "...", `...`, [...], or a PostgreSQL $tag$...$tag$)."""
    n, q = len(sql), sql[i]
    if q == "$":
        tag = DOLLAR_TAG.match(sql, i)
        if not tag:
            return i + 1
        close = sql.find(tag.group(), tag.end())
        return n if close < 0 else close + len(tag.group())
    close_char = "]" if q == "[" else q
    escapes = (engine == "mysql" and q in "'\"") or (
        engine == "postgres" and q == "'" and i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_")))
    j = i + 1
    while j < n:
        if escapes and sql[j] == "\\":
            j += 2
        elif sql[j] == close_char:
            if j + 1 < n and sql[j + 1] == close_char:
                j += 2
            else:
                return j + 1
        else:
            j += 1
    return n


def split_statements(sql, engine):
    """The non-empty statements of sql: text outside quotes and comments is split at ';', pieces holding only comments are dropped."""
    statements, current, meaningful = [], [], False
    n, i = len(sql), 0
    while i < n:
        c, two = sql[i], sql[i:i + 2]
        line_comment = (two == "--" and (engine != "mysql" or i + 2 >= n or sql[i + 2] in " \t\r\n\f")) or (c == "#" and engine == "mysql")
        if line_comment:
            end = sql.find("\n", i)
            i = n if end < 0 else end
        elif two == "/*":
            depth, j = 1, i + 2
            while j < n and depth:
                if engine == "postgres" and sql[j:j + 2] == "/*":
                    depth, j = depth + 1, j + 2
                elif sql[j:j + 2] == "*/":
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            current.append(" ")
            i = j
        elif c in "'\"`" or (c == "[" and engine == "mssql") or (c == "$" and engine == "postgres"):
            end = quoted_end(sql, i, engine)
            current.append(sql[i:end])
            meaningful = meaningful or end > i + 1 or c != "$"
            i = end
        elif c == ";":
            if meaningful:
                statements.append("".join(current).strip())
            current, meaningful, i = [], False, i + 1
        else:
            meaningful = meaningful or not c.isspace()
            current.append(c)
            i += 1
    if meaningful:
        statements.append("".join(current).strip())
    return statements


def refusals(sql, engine, allow_multi, read_only):
    problems = []
    if engine == "mysql" and re.search(r"/\*M?!", sql):
        problems.append("a MySQL executable comment (/*! ... */) can hide a second statement")
    command = CLIENT_COMMAND[engine].search(sql)
    if command:
        rest_of_line = sql[command.end():].split("\n", 1)[0]
        problems.append("client command line: " + (command.group().strip() + rest_of_line).strip())
    if engine == "mssql" and GO_LINE.search(sql):
        problems.append("GO batch separator")
    statements = split_statements(sql, engine)
    if not statements:
        problems.append("no statement")
    if len(statements) > 1 and not allow_multi:
        problems.append(f"{len(statements)} statements (one allowed; --allow-multi for a reviewed file)")
    if read_only:
        for statement in statements:
            first = re.match(r"\s*(\w+)", statement)
            if not first or first.group(1).lower() not in READ_ONLY_START:
                problems.append("not read only: " + statement[:40])
    return problems, statements


def idempotence_notes(statements):
    notes = []
    for statement in statements:
        text = re.sub(r"\s+", " ", statement).strip()
        low = text.lower()
        if re.match(r"create (table|database|schema)\b", low) and "if not exists" not in low and "object_id" not in low:
            notes.append("CREATE without IF NOT EXISTS fails the second time: " + text[:50])
        elif re.match(r"drop \w+ ", low) and "if exists" not in low:
            notes.append("DROP without IF EXISTS fails the second time: " + text[:50])
        elif re.match(r"insert\b", low) and not re.search(r"\bignore\b|on duplicate|on conflict|not exists|\bmerge\b", low):
            notes.append("plain INSERT adds the rows again on a second run: " + text[:50])
    return notes


def redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "REDACTED")
    return re.sub(r"(?i)\b(password|pwd)\s*=\s*[^;\s'\"]+", r"\1=REDACTED", text)


def find_client(name):
    found = shutil.which(name)
    if found:
        return found
    for pattern in FALLBACK_GLOBS.get(name, []):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    sys.exit(f"{name} was not found on PATH: install it, or borrow a container's client with --via <container>")


def build_command(args, sql):
    """(command, stdin text or None, environment, secrets, temp file or None) for the chosen engine."""
    spec = ENGINES[args.engine]
    env = dict(os.environ)
    password_var = spec["password_env"]
    if args.password_env:
        if args.password_env not in os.environ:
            sys.exit(f"environment variable {args.password_env} is not set")
        env[password_var] = os.environ[args.password_env]
    if args.trusted:
        for name in ("SQLCMDUSER", "SQLCMDPASSWORD"):
            env.pop(name, None)
    secrets = [env.get(password_var)]
    host = args.host or "127.0.0.1"
    temp = None
    stdin_text = None

    if args.engine == "mysql":
        flags = ["--host", host, "--user", args.user or "root", f"--connect-timeout={CONNECT_TIMEOUT}",
                 f"--init-command=SET SESSION MAX_EXECUTION_TIME={QUERY_TIMEOUT * 1000}",
                 "--batch", "--quick", "--default-character-set=utf8mb4"]
        if args.port:
            flags += ["--port", str(args.port)]
        if args.db:
            flags += ["--database", args.db]
        stdin_text = sql
    elif args.engine == "postgres":
        env["PGOPTIONS"] = f"-c statement_timeout={QUERY_TIMEOUT * 1000}"
        env["PGCONNECT_TIMEOUT"] = str(CONNECT_TIMEOUT)
        env["PGCLIENTENCODING"] = "UTF8"
        flags = ["-h", host, "-U", args.user or "postgres", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", "FETCH_COUNT=1000",
                 "-A", "-F", "\t", "-P", "footer=off"]
        if args.port:
            flags += ["-p", str(args.port)]
        if args.db:
            flags += ["-d", args.db]
        stdin_text = sql
    else:
        server = f"{host},{args.port}" if args.port else host
        flags = ["-S", server, "-l", str(CONNECT_TIMEOUT), "-t", str(QUERY_TIMEOUT), "-b", "-y", "8000", "-s", "\t", "-f", "65001"]
        flags += ["-E"] if args.trusted else ["-U", args.user or "sa"]
        if args.trust_cert:
            flags.append("-C")
        if args.db:
            flags += ["-d", args.db]
        if args.via:
            flags += ["-Q", sql]
        else:
            handle, name = tempfile.mkstemp(suffix=".sql")
            os.close(handle)
            temp = Path(name)
            temp.write_text(sql, encoding="utf-8")
            flags += ["-i", str(temp)]

    if args.via:
        pass_through = ["-e", password_var] if env.get(password_var) else []
        command = ["docker", "exec"] + (["-i"] if stdin_text is not None else []) + pass_through + [args.via, spec["container_exe"]] + flags
    else:
        command = [find_client(spec["exe"])] + flags
    return command, stdin_text, env, secrets, temp


def tidy(lines, engine):
    """sqlcmd pads every column to its width, prints a dashed rule under the header and a row count line at the end;
    none of that belongs in tab separated output (-W would trim the padding but cannot be combined with -y)."""
    if engine != "mssql":
        return lines
    kept = [l for l in lines if not re.match(r"^\(\d+ rows? affected\)\s*$", l)]
    if len(kept) > 1 and re.match(r"^[-\t ]+$", kept[1]):
        del kept[1]
    return ["\t".join(cell.strip() for cell in l.split("\t")) for l in kept if l.strip()]


def run(command, stdin_text, env, secrets, engine):
    process = subprocess.Popen(command, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    timed_out = []
    timer = threading.Timer(KILL_AFTER, lambda: (timed_out.append(1), process.kill()))
    timer.start()
    errors = []
    threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True).start()
    if stdin_text is not None:
        def feed():
            try:
                process.stdin.write(stdin_text.encode("utf-8"))
                process.stdin.close()
            except OSError:
                pass
        threading.Thread(target=feed, daemon=True).start()

    lines, truncated = [], False
    for raw in process.stdout:
        lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        if len(lines) > ROW_CAP + 2:
            truncated = True
            process.kill()
            break
    code = process.wait()
    timer.cancel()
    lines = tidy(lines, engine)
    if len(lines) > ROW_CAP + 1:
        truncated, lines = True, lines[:ROW_CAP + 1]
    print(redact("\n".join(lines), secrets))
    if truncated:
        print(f"[stopped at {ROW_CAP} rows]", file=sys.stderr)
    text = b"".join(errors).decode("utf-8", errors="replace").strip()
    if text:
        print(redact(text, secrets), file=sys.stderr)
    if timed_out:
        print(f"[killed after {KILL_AFTER} s]", file=sys.stderr)
        return EXIT_TIMEOUT
    if not truncated and TIMEOUT_MESSAGE[engine].search("\n".join(lines) + "\n" + text):
        print(f"[query timeout of {QUERY_TIMEOUT} s reached]", file=sys.stderr)
        return EXIT_TIMEOUT
    return 0 if truncated else code


def self_test():
    checks = [
        ("mysql", "SELECT 1", 1), ("mysql", "SELECT 1;", 1), ("mysql", "SELECT 1; DROP TABLE x", 2),
        ("mysql", "SELECT ';'", 1), ("mysql", "SELECT 'it''s; fine'", 1), ("mysql", "SELECT 'a\\'; DROP TABLE x; --'", 1),
        ("mysql", "SELECT 1--1; DROP TABLE x", 2), ("mysql", "SELECT 1 -- note; DROP TABLE x\n", 1), ("mysql", "SELECT 1 # a; b\n", 1),
        ("mysql", "SELECT `a;b` FROM t", 1), ("mysql", "SELECT 1 /* ; */", 1), ("mysql", "-- only a comment", 0),
        ("postgres", "SELECT $$a;b$$", 1), ("postgres", "SELECT $q$ a;b $q$; SELECT 2", 2), ("postgres", "SELECT E'a\\'; b'", 1),
        ("postgres", "SELECT 1 /* a /* b */ ; */", 1), ("postgres", "SELECT 1--x; DROP TABLE t\n", 1), ("postgres", "SELECT a[1] FROM t", 1),
        ("mssql", "SELECT [a;b] FROM t", 1), ("mssql", "SELECT 1; SELECT 2", 2), ("mssql", "SELECT 'x'';y'", 1),
    ]
    failed = 0
    for engine, sql, expected in checks:
        got = len(split_statements(sql, engine))
        if got != expected:
            failed += 1
            print(f"FAIL {engine}: {sql!r} expected {expected} statement(s), got {got}")
    refused = [("mysql", "SELECT 1 /*! ; DROP TABLE x */"), ("mysql", "system ls"), ("mysql", "\\! dir"), ("mysql", "delimiter //"),
               ("postgres", "\\! dir"), ("mssql", "SELECT 1\nGO"), ("mssql", ":r file.sql"), ("mssql", "!! dir")]
    for engine, sql in refused:
        if not refusals(sql, engine, True, False)[0]:
            failed += 1
            print(f"FAIL {engine}: {sql!r} should be refused")
    allowed = [("mysql", "SELECT source FROM t"), ("mysql", "SELECT\n  system AS s\nFROM t"), ("mssql", "SELECT 'GO'")]
    for engine, sql in allowed:
        if refusals(sql, engine, False, False)[0]:
            failed += 1
            print(f"FAIL {engine}: {sql!r} should be allowed")
    if not refusals("DELETE FROM t", "mysql", False, True)[0] or refusals("SELECT 1", "mysql", False, True)[0]:
        failed += 1
        print("FAIL read only")
    secret_text = redact("Server=a;Password=Hunter2;x pwd = abc and Hunter2 again", ["Hunter2"])
    if "Hunter2" in secret_text or "abc" in secret_text:
        failed += 1
        print("FAIL redact: " + secret_text)
    total = len(checks) + len(refused) + len(allowed) + 2
    print(f"{total - failed} of {total} checks passed")
    return 1 if failed else 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--engine", required=True, choices=sorted(ENGINES))
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--db")
    p.add_argument("--password-env", metavar="NAME", help="environment variable that holds the password (default MYSQL_PWD, PGPASSWORD, SQLCMDPASSWORD)")
    p.add_argument("--trusted", action="store_true", help="SQL Server Windows authentication")
    p.add_argument("--trust-cert", action="store_true", help="SQL Server: trust the server certificate (sqlcmd -C)")
    p.add_argument("--via", metavar="CONTAINER", help="run the client inside this running container")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("-e", dest="sql", metavar="SQL")
    source.add_argument("--file", metavar="PATH")
    p.add_argument("--allow-multi", action="store_true")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sql = args.sql if args.sql is not None else Path(args.file).read_text(encoding="utf-8-sig")
    problems, statements = refusals(sql, args.engine, args.allow_multi, args.read_only)
    if problems:
        print("REFUSED: " + "; ".join(problems), file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    for note in idempotence_notes(statements):
        print("note: " + note, file=sys.stderr)

    command, stdin_text, env, secrets, temp = build_command(args, sql)
    try:
        if args.dry_run:
            print(redact(subprocess.list2cmdline([str(c) for c in command]), secrets))
            print(f"stdin: {len(stdin_text)} characters of SQL" if stdin_text is not None else "stdin: none")
            return
        sys.exit(run(command, stdin_text, env, secrets, args.engine))
    finally:
        if temp:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
