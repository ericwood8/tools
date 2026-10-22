"""Replaces text in a file that may use CRLF, keeps the file's line endings and refuses unless the old text occurs the expected number of times.

As a module:   from edit_text import replace_in_file;  replace_in_file(path, old, new)       (old and new use \\n)
From a shell:  python edit_text.py FILE OLD_FILE NEW_FILE [count]    (old and new are read from files, so no shell quoting is involved)
"""
import io
import sys


def replace_in_file(path, old, new, count=1):
    with io.open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    found = text.count(old)
    if found != count:
        raise ValueError(f"{path}: expected {count} occurrence(s) of the old text, found {found}")
    text = text.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n") if crlf else text)


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    read = lambda p: io.open(p, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    replace_in_file(sys.argv[1], read(sys.argv[2]), read(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) == 5 else 1)
