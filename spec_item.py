"""Lists, moves and appends the numbered items of a spec file whose items start with `## <number>. ` (the CodeGenPossibilities spec.md and spec_completed.md).

  python spec_item.py list <spec.md> [--from N]                    one line per item: line number, heading
  python spec_item.py show <spec.md> N                             prints the item (the first one, when a number occurs twice)
  python spec_item.py move <spec.md> <completed.md> N [--heading "N. Name, shipped (2026-10-22)"]
                                                                   cuts item N out of the first file and appends it to the second
  python spec_item.py append <spec.md> <text file>                 appends the text (new items) to the end of the spec

An item runs from its `## ` heading to the line before the next `## ` heading (or the end of the file); text inside fenced code blocks is not
a heading. Line endings of each file are kept (CRLF stays CRLF). --heading replaces the heading line of the moved item. A number that occurs
more than once (an item shipped in parts) needs --occurrence K (1-based, default 1). Nothing is written unless the item is found.
"""
import io
import os
import re
import sys

def fix_path(path):
    """Git Bash spells C:/x as /c/x; a Windows Python does not understand that."""
    m = re.match(r"^/([a-zA-Z])/(.*)$", path) if os.name == "nt" else None
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else path


HEADING = re.compile(r"^## (\d+)\.\s")


def read(path):
    raw = io.open(path, encoding="utf-8", newline="").read()
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def write(path, text, crlf):
    io.open(path, "w", encoding="utf-8", newline="").write(text.replace("\n", "\r\n") if crlf else text)


def items(lines):
    """(start line index, number) of every item heading, ignoring fenced code."""
    found, fenced = [], False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (m := HEADING.match(line)):
            found.append((i, int(m.group(1))))
    return found


def span(lines, number, occurrence=1):
    headings = items(lines)
    starts = [k for k, (_, n) in enumerate(headings) if n == number]
    if len(starts) < occurrence:
        sys.exit(f"item {number} (occurrence {occurrence}) not found")
    k = starts[occurrence - 1]
    start = headings[k][0]
    end = next((i for i, line in enumerate(lines) if i > start and line.startswith("## ") and not _in_fence(lines, i)), len(lines))
    return start, end


def _in_fence(lines, index):
    return sum(1 for line in lines[:index] if line.startswith("```")) % 2 == 1


def option(args, name, default=None):
    if name in args:
        i = args.index(name)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    command = args.pop(0)
    args = [fix_path(a) for a in args]
    if command == "list" and args:
        floor = int(option(args, "--from", 0))
        lines = read(args[0])[0].split("\n")
        for i, line in enumerate(lines):
            if (m := HEADING.match(line)) and (i, int(m.group(1))) in items(lines) and int(m.group(1)) >= floor:
                print(f"{i + 1}: {line[3:]}")
    elif command == "show" and len(args) == 2:
        lines = read(args[0])[0].split("\n")
        start, end = span(lines, int(args[1]))
        print("\n".join(lines[start:end]).rstrip())
    elif command == "move":
        heading, occurrence = option(args, "--heading"), int(option(args, "--occurrence", 1))
        if len(args) != 3:
            sys.exit(__doc__)
        spec_path, done_path, number = args[0], args[1], int(args[2])
        text, crlf = read(spec_path)
        lines = text.split("\n")
        start, end = span(lines, number, occurrence)
        block = lines[start:end]
        if heading:
            block[0] = "## " + heading
        while block and not block[-1].strip():
            block.pop()
        done, done_crlf = read(done_path)
        write(done_path, done.rstrip("\n") + "\n\n" + "\n".join(block) + "\n", done_crlf)
        rest = lines[:start] + lines[end:]
        write(spec_path, re.sub(r"\n{3,}", "\n\n", "\n".join(rest)).rstrip("\n") + "\n", crlf)
        print(f"moved item {number} ({len(block)} lines) to {done_path}")
    elif command == "append" and len(args) == 2:
        text, crlf = read(args[0])
        add = read(args[1])[0]
        write(args[0], text.rstrip("\n") + "\n\n" + add.strip("\n") + "\n", crlf)
        print(f"appended {len(add.splitlines())} lines to {args[0]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
