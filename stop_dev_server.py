"""Stops a leftover dev server (an ASP.NET API started with `dotnet run` or its published .exe) that holds a file or a port. Windows.

  python stop_dev_server.py --port 5090                      the process listening on port 5090
  python stop_dev_server.py --path InvoiceSystemMySql        every candidate whose command line or program path contains the text
  python stop_dev_server.py --name InvoiceSystem.Api.exe     every process with that name (wildcards allowed: "*.Api.exe")
  add --dry-run to list what would be stopped; the filters combine (a process must match every one given)

At least one filter is required, so it never stops "everything". Only candidates are considered: dotnet.exe and *.Api.exe by default, or the
names given with --candidates (comma separated, wildcards allowed, for example "dotnet.exe,node.exe"). Never stopped, whatever the filters say:
this tool and its parent processes (your shell), and the build servers that are also dotnet.exe (MSBuild nodes, the Roslyn VBCSCompiler, the
Razor server), unless --include-build-servers. Every process is printed before it is stopped, with its command line shortened. A process that
was already gone counts as stopped. Exit codes: 0 stopped or nothing matched, 1 a process could not be stopped, 2 usage.

Paths: pass --path text with forward slashes or backslashes; both are matched against the command line and the program path.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

DEFAULT_CANDIDATES = ["dotnet.exe", "*.Api.exe"]
BUILD_SERVER = re.compile(r"MSBuild\.dll|VBCSCompiler|build-server|-nodeReuse|Razor|BuildHost|\bMSBuildTaskHost", re.IGNORECASE)


def processes():
    command = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        sys.exit("could not list processes: " + result.stderr.strip())
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]


def listening_pids(port):
    result = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True)
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            pids.add(int(parts[4]))
    return pids


def ancestors(by_pid, pid):
    found = set()
    while pid in by_pid and pid not in found:
        found.add(pid)
        pid = by_pid[pid].get("ParentProcessId") or 0
    return found


def normal(text):
    return (text or "").replace("\\", "/").lower()


def main():
    args = sys.argv[1:]
    port = path = name = None
    dry = include_build = False
    candidates = DEFAULT_CANDIDATES
    while args:
        flag = args.pop(0)
        if flag == "--dry-run":
            dry = True
        elif flag == "--include-build-servers":
            include_build = True
        elif flag in ("--port", "--path", "--name", "--candidates") and args:
            value = args.pop(0)
            if flag == "--port":
                if not value.isdigit():
                    sys.exit("--port needs a number")
                port = int(value)
            elif flag == "--path":
                path = normal(value)
            elif flag == "--name":
                name = value
            else:
                candidates = [c.strip() for c in value.split(",") if c.strip()]
        else:
            sys.exit(__doc__)
    if port is None and path is None and name is None:
        sys.exit(__doc__)

    table = processes()
    by_pid = {p["ProcessId"]: p for p in table}
    protected = ancestors(by_pid, os.getpid())
    owners = listening_pids(port) if port is not None else None

    matched = []
    for p in table:
        pid, exe = p["ProcessId"], p.get("Name") or ""
        if pid in protected:
            continue
        if not any(fnmatch.fnmatch(exe.lower(), c.lower()) for c in candidates):
            continue
        line = p.get("CommandLine") or ""
        if not include_build and BUILD_SERVER.search(line):
            continue
        if owners is not None and pid not in owners:
            continue
        if path is not None and path not in normal(line) and path not in normal(p.get("ExecutablePath")):
            continue
        if name is not None and not fnmatch.fnmatch(exe.lower(), name.lower()):
            continue
        matched.append(p)

    if not matched:
        print("nothing matched")
        return 0
    failed = 0
    for p in matched:
        line = (p.get("CommandLine") or p.get("ExecutablePath") or "").strip()
        shown = line if len(line) <= 140 else line[:137] + "..."
        print(f"{'would stop' if dry else 'stopping'} {p['ProcessId']} {p['Name']}  {shown}")
        if dry:
            continue
        done = subprocess.run(["taskkill", "/PID", str(p["ProcessId"]), "/F"], capture_output=True, text=True)
        if done.returncode != 0 and "not found" not in (done.stdout + done.stderr).lower():
            failed += 1
            print("  could not stop it: " + (done.stderr or done.stdout).strip())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
