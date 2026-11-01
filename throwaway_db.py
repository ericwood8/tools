"""Starts, uses and removes a throwaway MySQL server in a Docker container, so a test never touches a real database or someone else's container.

  python throwaway_db.py up                                  start zz-mysql on 127.0.0.1:3307 (image mysql:8.4) and wait until it answers
  python throwaway_db.py up --name zz-trg --port 3308 --skip-log-bin      (lets a login without SUPER create triggers)
  python throwaway_db.py up --server-arg=--lower-case-table-names=1       (any other server option: write it with `=`)
  python throwaway_db.py sql zz-mysql -e "SELECT VERSION()"
  python throwaway_db.py sql zz-mysql --file schema.sql --db shop
  python throwaway_db.py list                                containers made by this tool
  python throwaway_db.py down zz-mysql                       remove one;  `down --all` removes every container this tool made

Safety rules built in:
  - names must start with `zz-`; `down` only removes containers that start with `zz-` AND carry this tool's label,
    so a user's own container is never touched, even with the same name prefix
  - the image must already be on this machine; the tool never pulls (a pull is a download the user should approve):
    it stops with exit code 3 and says which `docker pull` would be needed
  - the port is bound to 127.0.0.1 only, and `up` refuses a port that is already in use
  - the root password is random per run (or THROWAWAY_DB_PASSWORD); it is kept in a file under the temp folder
    (the path is printed) and sent to the client in the MYSQL_PWD variable, never on a command line
  - `up` waits for a real TCP connection, because MySQL's first-run setup answers a socket ping and then restarts

`sql` runs the mysql client inside the container (so no client is needed on the host): -e "SQL" or --file F.sql (read on stdin),
--db NAME selects a database, --user NAME and --password-env VAR connect as another login than root.
The `mysql` client stops at the first error, so a script ends there; the exit code is the client's.
Exit codes: 0 ok, 2 usage or a refused name, 3 image not local, 4 port busy, 5 server did not become ready in time, otherwise docker's or the client's.
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LABEL = "throwaway_db=1"
PREFIX = "zz-"


def docker(*args, check=False, text=True, input_text=None, capture=True, extra_env=None):
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    return subprocess.run(["docker", *args], capture_output=capture, text=text, input=input_text, check=check, env=env)


def pwd_file(name):
    return Path(tempfile.gettempdir()) / f"throwaway_{name}.pwd"


def password_for(name):
    if os.environ.get("THROWAWAY_DB_PASSWORD"):
        return os.environ["THROWAWAY_DB_PASSWORD"]
    f = pwd_file(name)
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def check_name(name):
    if not name.startswith(PREFIX):
        print(f"refused: the name must start with {PREFIX!r} (got {name!r}); this tool only manages its own containers", file=sys.stderr)
        sys.exit(2)


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ours(name):
    r = docker("ps", "-a", "--filter", f"name=^{name}$", "--filter", f"label={LABEL}", "--format", "{{.Names}}")
    return r.returncode == 0 and name in r.stdout.split()


def cmd_up(a):
    check_name(a.name)
    probe = docker("image", "inspect", a.image)
    if probe.returncode != 0 and "no such image" in (probe.stderr or "").lower():
        # Docker Desktop's containerd image store can fail `image inspect` by name for an image that is listed and runs; the listing is the second opinion
        listed = docker("images", "-q", a.image)
        if listed.returncode == 0 and listed.stdout.strip():
            probe = listed
    if probe.returncode != 0:
        if "no such image" in (probe.stderr or "").lower():
            print(f"image {a.image} is not on this machine. This tool does not pull. If the user agrees to the download, run: docker pull {a.image}", file=sys.stderr)
            return 3
        print(f"docker could not inspect {a.image}: {(probe.stderr or '').strip()}", file=sys.stderr)
        return probe.returncode or 2
    if port_in_use(a.port):
        print(f"port {a.port} on 127.0.0.1 is already in use; pick another with --port", file=sys.stderr)
        return 4
    if docker("ps", "-a", "--filter", f"name=^{a.name}$", "--format", "{{.Names}}").stdout.strip():
        print(f"a container named {a.name} already exists; remove it with: python throwaway_db.py down {a.name}", file=sys.stderr)
        return 2
    pw = os.environ.get("THROWAWAY_DB_PASSWORD") or secrets.token_urlsafe(12)
    pwd_file(a.name).write_text(pw, encoding="utf-8")
    server_args = list(a.server_arg) + (["--skip-log-bin"] if a.skip_log_bin else [])
    r = docker("run", "-d", "--rm", "--pull=never", "--name", a.name, "--label", LABEL, "-e", "MYSQL_ROOT_PASSWORD",
               "-p", f"127.0.0.1:{a.port}:3306", a.image, *server_args, extra_env={"MYSQL_ROOT_PASSWORD": pw})
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    deadline = time.time() + a.wait
    while time.time() < deadline:
        ping = docker("exec", "-e", "MYSQL_PWD", a.name, "mysql", "-h", "127.0.0.1", "-P", "3306", "-uroot", "-e", "SELECT 1", extra_env={"MYSQL_PWD": pw})
        if ping.returncode == 0:
            print(f"ready: {a.name} on 127.0.0.1:{a.port} ({a.image}); root password in {pwd_file(a.name)}")
            return 0
        time.sleep(2)
    print(f"{a.name} did not answer within {a.wait} s; see: docker logs {a.name}", file=sys.stderr)
    return 5


def cmd_sql(a):
    check_name(a.name)
    pw = os.environ.get(a.password_env) if a.password_env else password_for(a.name)
    if not pw:
        print(f"no password: no {pwd_file(a.name)} and no environment variable; was {a.name} started by this tool?", file=sys.stderr)
        return 2
    if bool(a.e) == bool(a.file):
        print("give exactly one of -e SQL or --file F.sql", file=sys.stderr)
        return 2
    base = ["exec", "-i", "-e", "MYSQL_PWD", a.name, "mysql", f"-u{a.user}"]
    if a.db:
        base.append(a.db)
    if a.e:
        r = docker(*base, "-e", a.e, extra_env={"MYSQL_PWD": pw})
    else:
        f = Path(a.file)
        if not f.is_file():
            print(f"file not found: {a.file} (Windows Python needs a C:/x path, not a Git Bash /tmp/x or /c/x path)", file=sys.stderr)
            return 2
        r = docker(*base, input_text=f.read_text(encoding="utf-8"), extra_env={"MYSQL_PWD": pw})
    sys.stdout.write(r.stdout)
    err = "\n".join(l for l in r.stderr.splitlines() if "Using a password on the command line" not in l)
    if err.strip():
        sys.stderr.write(err + "\n")
    return r.returncode


def cmd_list(a):
    r = docker("ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")
    sys.stdout.write(r.stdout if r.stdout.strip() else "(none)\n")
    return 0


def cmd_down(a):
    if a.all:
        names = docker("ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}").stdout.split()
        names = [n for n in names if n.startswith(PREFIX)]
    else:
        if not a.name:
            print("give a container name or --all", file=sys.stderr)
            return 2
        check_name(a.name)
        if not ours(a.name):
            print(f"refused: {a.name} is not a container made by this tool (no {LABEL} label), or it does not exist", file=sys.stderr)
            return 2
        names = [a.name]
    for n in names:
        docker("rm", "-f", n)
        pwd_file(n).unlink(missing_ok=True)
        print(f"removed {n}")
    if not names:
        print("nothing to remove")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    ap = argparse.ArgumentParser(add_help=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up")
    up.add_argument("--name", default="zz-mysql")
    up.add_argument("--port", type=int, default=3307)
    up.add_argument("--image", default="mysql:8.4")
    up.add_argument("--wait", type=int, default=120)
    up.add_argument("--server-arg", action="append", default=[])
    up.add_argument("--skip-log-bin", action="store_true")
    sq = sub.add_parser("sql")
    sq.add_argument("name")
    sq.add_argument("-e")
    sq.add_argument("--file")
    sq.add_argument("--db")
    sq.add_argument("--user", default="root")
    sq.add_argument("--password-env")
    sub.add_parser("list")
    dn = sub.add_parser("down")
    dn.add_argument("name", nargs="?")
    dn.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    try:
        subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, check=True, timeout=30)
    except Exception:
        print("docker is not running or not installed (docker version failed)", file=sys.stderr)
        return 2
    return {"up": cmd_up, "sql": cmd_sql, "list": cmd_list, "down": cmd_down}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
