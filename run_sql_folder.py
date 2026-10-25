"""Runs every .sql file of a folder against one SQL Server database with sqlcmd and reports which ran.

  python run_sql_folder.py --server ERICSMINIPC --database AvatarDev --dir C:/Github/CodeGenNew/Output/AvatarDev.App/sql [--user NAME] [--stop-on-fail]

Windows authentication unless --user is given; then the password comes from SQLCMDPASSWORD (never from the command line). Files run in name order. A file that fails is tried
again after the others, as long as a pass makes progress, so scripts that need an object another script creates (a procedure that calls a view) end up in a working order. Prints
one line per file (ok or the first error line) and ends with `ok=N failed=M`; exit code 0 only when every file ran. sqlcmd runs with -b (stop on error) and -I (quoted identifiers).
Scripts change the database: run this against a database you may change.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def fix_path(path):
    m = re.match(r"^/([a-zA-Z])/(.*)$", path) if os.name == "nt" else None
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else path


def run(file, args):
    command = ["sqlcmd", "-S", args.server, "-d", args.database, "-b", "-I", "-i", str(file)]
    command += ["-U", args.user] if args.user else ["-E"]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=args.timeout)
    if result.returncode == 0:
        return None
    lines = [l.strip() for l in (result.stdout + result.stderr).replace("\r", "").split("\n") if l.strip()]
    return lines[0] if lines else f"exit {result.returncode}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--user")
    parser.add_argument("--timeout", type=int, default=120, help="seconds per file")
    parser.add_argument("--stop-on-fail", action="store_true")
    args = parser.parse_args()
    if args.user and not os.environ.get("SQLCMDPASSWORD"):
        sys.exit("--user needs the password in SQLCMDPASSWORD")
    files = sorted(Path(fix_path(args.dir)).glob("*.sql"), key=lambda p: p.name.lower())
    if not files:
        sys.exit("no .sql files in " + args.dir)

    pending, done, errors = files, 0, {}
    while pending:
        failed = []
        for file in pending:
            error = run(file, args)
            if error is None:
                done += 1
                errors.pop(file, None)
            else:
                errors[file] = error
                failed.append(file)
                if args.stop_on_fail:
                    print(f"FAIL {file.name}: {error}")
                    sys.exit(1)
        if len(failed) == len(pending):
            break
        pending = failed
    for file in files:
        print(f"{'FAIL' if file in errors else 'ok  '} {file.name}" + (f": {errors[file]}" if file in errors else ""))
    print(f"ok={done} failed={len(errors)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
