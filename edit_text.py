"""Replaces text in a file that may use CRLF, keeps the file's line endings and refuses unless the old text occurs the expected number of times.

As a module:   from edit_text import replace_in_file, replace_many
               replace_in_file(path, old, new)                          (old and new use \\n)
               replace_many(path, [(old1, new1), (old2, new2, count)])  (all or nothing: the file is written only when every pair matched)
From a shell:  python edit_text.py FILE OLD_FILE NEW_FILE [count]       (old and new are read from files, so no shell quoting is involved)
               python edit_text.py FILE --json EDITS.json               (EDITS.json: [{"old": "...", "new": "...", "count": 1}, ...], applied in order)

Each pair sees the text the earlier pairs produced. Text is never treated as a pattern, so `$` and `\\` in the new text are literal.
A file with mixed line endings is written with CRLF throughout.
"""
import io
import json
import sys


def replace_many(path, edits):
    with io.open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    for number, edit in enumerate(edits, 1):
        old, new = edit[0], edit[1]
        count = edit[2] if len(edit) > 2 else 1
        found = text.count(old)
        if found != count:
            raise ValueError(f"{path}: edit {number}: expected {count} occurrence(s) of the old text, found {found}")
        text = text.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n") if crlf else text)


def replace_in_file(path, old, new, count=1):
    replace_many(path, [(old, new, count)])


def _read(path):
    return io.open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3 and args[1] == "--json":
        edits = json.loads(_read(args[2]))
        replace_many(args[0], [(e["old"], e["new"], e.get("count", 1)) for e in edits])
    elif len(args) in (3, 4):
        replace_in_file(args[0], _read(args[1]), _read(args[2]), int(args[3]) if len(args) == 4 else 1)
    else:
        sys.exit(__doc__)
