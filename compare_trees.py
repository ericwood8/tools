"""Compares two source trees by file name: which files exist in both and are the same, which differ, which exist on one side only.

  python compare_trees.py --a <generated root> --b <hand-written root> --ext .cs,.ts [--dirs A1,A2] [--bdirs B1,B2] [--ignore-prefix E_] [--detail]

Files are matched by lower-cased name (a prefix such as E_ can be ignored), wherever they sit under the chosen folders. Two files are "same" when they
are equal after removing blank lines, `//` comments (also `///`) and leading and trailing blanks, so line endings, indentation and comments do not count.
--dirs / --bdirs are folders under the roots to search (default: the roots); bin, obj, node_modules, dist, .angular, .git and TestResults are skipped.
--detail prints a line count for each different pair. Example (generated TimeEntry against the hand-written one):

  python compare_trees.py --a C:/Samples/TimeEntryServer_CodeGen --dirs TimeEntry.Api --b C:/Github/TimeEntryServer --bdirs TimeEntry.ApiService,TimeEntry.Common --ext .cs --ignore-prefix E_
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

def fix_path(path):
    """Git Bash spells C:/x as /c/x; a Windows Python does not understand that."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", path) if os.name == "nt" else None
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else path


SKIP = {"bin", "obj", "node_modules", "dist", ".angular", ".git", "TestResults", ".vs"}


def index(root, dirs, extensions, prefix):
    found = defaultdict(list)
    for folder in dirs or [""]:
        base = Path(root, folder)
        if not base.exists():
            continue
        for current, names, files in os.walk(base):
            names[:] = [n for n in names if n not in SKIP]
            for file in files:
                if not file.lower().endswith(extensions):
                    continue
                key = file.lower()
                if prefix and key.startswith(prefix.lower()):
                    key = key[len(prefix):]
                found[key].append(Path(current, file))
    return found


def normal(path):
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    lines = (line.strip() for line in text.split("\n"))
    return [line for line in lines if line and not line.startswith("//")]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--dirs", default="")
    p.add_argument("--bdirs", default="")
    p.add_argument("--ext", required=True)
    p.add_argument("--ignore-prefix", default="")
    p.add_argument("--detail", action="store_true")
    o = p.parse_args()
    o.a, o.b = fix_path(o.a), fix_path(o.b)
    extensions = tuple(e if e.startswith(".") else "." + e for e in o.ext.lower().split(","))
    a = index(o.a, [d for d in o.dirs.split(",") if d], extensions, o.ignore_prefix)
    b = index(o.b, [d for d in (o.bdirs or o.dirs).split(",") if d], extensions, o.ignore_prefix)

    same, different = [], []
    for key, files in sorted(a.items()):
        if key not in b:
            continue
        text = normal(files[0])
        if any(normal(other) == text for other in b[key]):
            same.append(files[0].name)
        else:
            detail = f": {len(text)} lines against {len(normal(b[key][0]))}" if o.detail else ""
            different.append(files[0].name + detail)
    only_a = sorted(f[0].name for k, f in a.items() if k not in b)
    only_b = sorted(f[0].name for k, f in b.items() if k not in a)

    print(f"matched by name: {len(same) + len(different)}   same: {len(same)}   different: {len(different)}   only in A: {len(only_a)}   only in B: {len(only_b)}")
    for title, names in (("same", same), ("different", different), ("only in A (" + o.a + ")", only_a), ("only in B (" + o.b + ")", only_b)):
        print(f"\n{title} ({len(names)}):" + ("\n  " + "\n  ".join(names) if names and title != "same" else (" " + ", ".join(names) if names else "")))


if __name__ == "__main__":
    sys.exit(main())
