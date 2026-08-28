"""Join hard-wrapped prose in a markdown file back into one line per paragraph.

    python3 scripts/unwrap_markdown.py CHANGELOG.md ARCHITECTURE.md

The docs are soft-wrapped by the editor and by GitHub, so a hard break
inside a paragraph buys nothing and costs plenty: an edit anywhere in a
paragraph reflows every line below it, and the diff then shows the whole
paragraph as changed.  This unwraps in place.

Fenced code, indented code, headings, rules and blank lines pass through
untouched; a list item keeps its marker and absorbs its continuation
lines; a line ending in a hard break stays broken.  Before writing, the
file's words are compared with the original's, whitespace collapsed —
proof that text moved between lines but was never altered.  If they
differ at all, nothing is written.
"""

import re
import sys

FENCE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
INDENTED_CODE = re.compile(r"^ {4,}\S")
HARD_BREAK = re.compile(r"(  |\\)$")


def unwrap(text):
    """Return text with every wrapped paragraph joined onto one line."""
    out, buf, indent = [], [], ""
    in_fence = fence_mark = None

    def flush():
        nonlocal buf, indent
        if buf:
            out.append(indent + " ".join(buf))
            buf, indent = [], ""

    for line in text.split("\n"):
        fence = FENCE.match(line)
        if in_fence:
            # Inside a code block nothing is prose; only the closing
            # fence, in the same character it opened with, ends it.
            out.append(line)
            if fence and fence.group(1)[0] == fence_mark:
                in_fence = False
            continue
        if fence:
            flush()
            out.append(line)
            in_fence, fence_mark = True, fence.group(1)[0]
            continue
        if not line.strip() or HEADING.match(line) or RULE.match(line):
            flush()
            out.append(line)
            continue
        item = ITEM.match(line)
        if item:
            # A marker always starts a new line; what follows it, until
            # the next marker or blank line, belongs to this item.
            flush()
            indent = item.group(1)
            buf = [line[len(indent):]]
            continue
        if INDENTED_CODE.match(line) and not buf:
            out.append(line)
            continue
        if buf and HARD_BREAK.search(buf[-1]):
            flush()
        if not buf:
            indent = re.match(r"\s*", line).group(0)
        buf.append(line.strip())
    flush()
    return "\n".join(out)


def words(text):
    return re.sub(r"\s+", " ", text).strip()


def main(paths):
    for path in paths:
        with open(path) as fh:
            before = fh.read()
        after = unwrap(before)
        if words(before) != words(after):
            sys.exit(f"{path}: words changed, not just line breaks — refusing to write")
        with open(path, "w") as fh:
            fh.write(after)
        print(f"{path}: {len(before.splitlines())} -> {len(after.splitlines())} lines")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip())
    main(sys.argv[1:])
