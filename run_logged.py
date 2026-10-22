"""Runs a long command, writes everything it prints to a log file, and ends with one status line. Start it with Bash `run_in_background: true`.

  python run_logged.py <log file> [--tail N] [--hide REGEX] -- <command> [args...]

The harness notifies you when this process exits, so there is no polling, no `sleep` and no Monitor loop. Do not put it in a `( ... ) &` subshell:
the outer command then ends at once and the notification arrives before the work is done. The log (and the last N lines, default 40, minus lines
matching --hide) are printed at the end, followed by `FINISHED exit=<code> seconds=<n>`. The log name is yours: use a new one per run, so a
notification from an earlier run is never mistaken for this one. The exit code of this process is the command's.
On Windows name a program Windows can start: "C:/Program Files/Git/bin/bash.exe" script.sh (a bare `bash` is WSL), dotnet, npm.cmd, python.
"""
import re
import subprocess
import sys
import time
from pathlib import Path


def main():
    args = sys.argv[1:]
    if "--" not in args or len(args) < 3:
        sys.exit(__doc__)
    split = args.index("--")
    head, command = args[:split], args[split + 1:]
    if not head or not command:
        sys.exit(__doc__)
    log, tail, hide = Path(head[0]), 40, None
    rest = head[1:]
    while rest:
        flag, value = rest[0], rest[1] if len(rest) > 1 else None
        if flag == "--tail" and value:
            tail = int(value)
        elif flag == "--hide" and value:
            hide = re.compile(value)
        else:
            sys.exit(__doc__)
        rest = rest[2:]

    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        code = subprocess.call(command, stdout=out, stderr=subprocess.STDOUT)
    seconds = round(time.time() - started)
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"FINISHED exit={code} seconds={seconds}\n")
    lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if not (hide and hide.search(l))]
    print("\n".join(lines[-tail:]))
    sys.exit(code)


if __name__ == "__main__":
    main()
