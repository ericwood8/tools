"""Writes schema.sql and seed.sql for the dbo schema of a SQL Server database, read from the catalog with sqlcmd (no SMO, no export wizard).

  python mssql_gen_scripts.py --server MYPC --db Shop --trusted --trust-cert --out C:/work/shop_scripts
  python mssql_gen_scripts.py --server MYPC --db Shop --user app --out C:/work/shop_scripts --disable-triggers
  python mssql_gen_scripts.py --server MYPC --db Shop --trusted --only schema

The scripts are re-runnable (every object is guarded; seed inserts only into empty tables) and are meant to be applied to an EMPTY database
that you made for the purpose. Apply them with the same sqlcmd flags this tool uses, from the output folder with relative file names:
  cd C:/work/shop_scripts
  sqlcmd -S MYPC -E -C -I -f 65001 -b -d Shop_copy -i schema.sql
  sqlcmd -S MYPC -E -C -I -f 65001 -b -d Shop_copy -i seed.sql
-I (quoted identifiers on) is needed for persisted computed columns and filtered indexes; -f 65001 reads and writes UTF-8 (without it a non-ASCII
value is garbled and can overflow its column). Use a relative path or backslashes after -i: sqlcmd reads a forward-slash path such as
C:/Users/me/x.sql as `C:` plus switches (/U becomes -U) and fails with "The -E and the -U/-P options are mutually exclusive" or "Access is denied".
The files are UTF-8 without a BOM, with CRLF line endings. Tables are seeded parents first (by foreign-key depth); a cycle of foreign keys
between tables is not resolved and needs its constraints disabled while the seed runs.

What it covers and what it leaves out is listed at the top of mssql_gen_scripts.sql (beside this file). In short: dbo only; no sequences,
synonyms, user-defined types, columnstore or full-text indexes, image/text/ntext/geometry columns, or history-table rows.
Tested by a round trip into an empty database: values, counts, keys, indexes, a trigger and a system-versioned table came back the same.

Options:
  --server NAME       SQL Server instance (required)
  --db NAME           database to read (required)
  --trusted           Windows authentication (default when --user is not given)
  --user NAME         SQL login; the password is read from SQLCMDPASSWORD (never a command-line option)
  --trust-cert        pass -C (trust the server certificate) - for a development server with a self-signed certificate
  --out DIR           where to write the files (default: the current folder)
  --only schema|seed  write just one of them
  --disable-triggers  wrap each seed insert in DISABLE TRIGGER ALL / ENABLE TRIGGER ALL (otherwise a trigger fires during the seed)
  --sqlcmd PATH       sqlcmd to use (default: sqlcmd on PATH)

Reading the catalog is read-only. Exit codes: 0 written, 1 sqlcmd reported an error (nothing is overwritten), 2 usage problem.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQL_FILE = HERE / "mssql_gen_scripts.sql"
ERROR_LINE = re.compile(r"^(Msg \d+, Level \d+|Sqlcmd: Error|Sqlcmd: )")


def run_mode(args, mode):
    cmd = [args.sqlcmd, "-S", args.server, "-d", args.db, "-I", "-f", "65001", "-y", "0"]
    if args.user:
        cmd += ["-U", args.user]
    else:
        cmd += ["-E"]
    if args.trust_cert:
        cmd += ["-C"]
    cmd += ["-i", str(SQL_FILE), "-v", f"Mode={mode}", f"DisableTriggers={1 if args.disable_triggers else 0}"]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    text = r.stdout.decode("utf-8", errors="replace")
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").split("\n")]
    errors = [l for l in lines if ERROR_LINE.match(l)]
    if r.returncode != 0 or errors:
        sys.stderr.write(f"sqlcmd failed for {mode}:\n")
        for l in (errors or lines)[:10]:
            sys.stderr.write("  " + l + "\n")
        err = r.stderr.decode("utf-8", errors="replace").strip()
        if err:
            sys.stderr.write("  " + err.splitlines()[0] + "\n")
        return None
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--server", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--trusted", action="store_true")
    ap.add_argument("--user")
    ap.add_argument("--trust-cert", action="store_true")
    ap.add_argument("--out", default=".")
    ap.add_argument("--only", choices=["schema", "seed"])
    ap.add_argument("--disable-triggers", action="store_true")
    ap.add_argument("--sqlcmd", default=shutil.which("sqlcmd") or "sqlcmd")
    args = ap.parse_args(argv)
    if args.user and not os.environ.get("SQLCMDPASSWORD"):
        print("--user needs the password in the SQLCMDPASSWORD environment variable", file=sys.stderr)
        return 2
    if not SQL_FILE.is_file():
        print(f"missing {SQL_FILE}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for mode in (["schema", "seed"] if not args.only else [args.only]):
        text = run_mode(args, mode)
        if text is None:
            return 1
        results[mode] = text
    for mode, text in results.items():
        target = out / f"{mode}.sql"
        target.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        print(f"wrote {target} ({len(text.splitlines())} lines)")
    print("apply to an EMPTY database, from that folder with relative names: sqlcmd -S <server> -E -C -I -f 65001 -b -d <empty db> -i schema.sql   (then seed.sql)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
