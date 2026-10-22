"""Installs and runs the tests of a generated React or Angular app, and prints the summary.

  python run_frontend_tests.py <generated app folder>      (the folder that holds package.json, for example <out>/frontend)

React runs `npx vitest run`; Angular runs `npm test -- --watch=false` (a project for Angular 21 or later runs Vitest on jsdom:
set AngularVersion=22 in the project file). `npm install` runs only when node_modules is missing. Exit code is the test run's.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

TAIL_LINES = 25
SUMMARY_WORDS = ("Test Files", "Tests ", "Duration", "FAIL", "AssertionError", "Error:", "TOTAL", "Executed", "passed", "failed")


def npm(*args, folder):
    executable = shutil.which("npm") or "npm"
    return subprocess.run([executable, *args], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    package = folder / "package.json"
    if not package.exists():
        sys.exit(f"{package} does not exist")
    dependencies = json.loads(package.read_text(encoding="utf-8"))
    names = {**dependencies.get("dependencies", {}), **dependencies.get("devDependencies", {})}
    angular = "@angular/core" in names

    if not (folder / "node_modules").exists():
        installed = npm("install", "--no-audit", "--no-fund", folder=folder)
        if installed.returncode != 0:
            sys.exit("npm install failed:\n" + installed.stderr[-2000:])
    if angular:
        result = npm("test", "--", "--watch=false", folder=folder)
    else:
        result = subprocess.run([shutil.which("npx") or "npx", "vitest", "run"], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = (result.stdout + result.stderr).strip().splitlines()
    summary = [line for line in text if any(word in line for word in SUMMARY_WORDS)]
    print("\n".join(summary[-TAIL_LINES:] or text[-TAIL_LINES:]))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
