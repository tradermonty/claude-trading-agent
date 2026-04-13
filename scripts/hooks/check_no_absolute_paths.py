#!/usr/bin/env python3
"""Pre-commit hook: detect absolute paths with usernames (repo portability issue).

Matches /Users/<name>/ and /home/<name>/ patterns.
Suppress false positives with a ``# noqa: absolute-path`` comment on the same line.
"""

import re
import sys

PATTERN = re.compile(r"/(?:Users|home)/[^/\s]+/")
SUPPRESS = "noqa: absolute-path"


def main() -> int:
    errors = 0
    for path in sys.argv[1:]:
        try:
            lines = open(path, encoding="utf-8", errors="replace").readlines()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(lines, 1):
            if PATTERN.search(line) and SUPPRESS not in line:
                print(f"{path}:{lineno}: absolute path detected")
                errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
