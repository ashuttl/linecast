#!/usr/bin/env python3
"""Point the README's relative links at one commit, for PyPI.

The README refers to its screenshots and to the other pages in the
repository by relative path, so GitHub shows each branch its own: next
shows next's screenshots, main shows main's.  PyPI renders the same file
with no repository to resolve those paths in, so the package build runs
this first, and the copy in the package points at the commit it was
built from: an image at its raw file, a page at its GitHub view.

    python scripts/pin_readme.py README.md ashuttl/linecast <commit>

It rewrites the file in place, and fails if a relative link is left that
it could not pin, rather than let a broken image reach PyPI.
"""

import re
import sys

# A link or an image: the text in brackets, then the target in parens.
# The text may hold one level of brackets, for a badge inside a link.
LINK = re.compile(r"(!?)(\[(?:[^\[\]]|\[[^\[\]]*\])*\]\()([^)\s]+)(\))")
SRC = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")')
ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/)", re.I)


def pin(text, repo, ref):
    raw = f"https://raw.githubusercontent.com/{repo}/{ref}/"
    page = f"https://github.com/{repo}/blob/{ref}/"

    def link(m):
        bang, head, target, tail = m.groups()
        if ABSOLUTE.match(target):
            return m.group(0)
        return f"{bang}{head}{(raw if bang else page)}{target}{tail}"

    def src(m):
        head, target, tail = m.groups()
        return m.group(0) if ABSOLUTE.match(target) else f"{head}{raw}{target}{tail}"

    return SRC.sub(src, LINK.sub(link, text))


def leftovers(text):
    found = [m.group(3) for m in LINK.finditer(text) if not ABSOLUTE.match(m.group(3))]
    found += [m.group(2) for m in SRC.finditer(text) if not ABSOLUTE.match(m.group(2))]
    return found


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip().split("\n\n")[2])
    path, repo, ref = sys.argv[1:]
    with open(path, encoding="utf-8") as f:
        text = pin(f.read(), repo, ref)
    left = leftovers(text)
    if left:
        raise SystemExit(f"pin_readme: left relative: {', '.join(left)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
