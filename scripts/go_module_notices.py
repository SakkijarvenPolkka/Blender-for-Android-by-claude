#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Third-party notices of a Go executable: the license files (LICENSE, NOTICE, COPYING, PATENTS) of
Go's standard library and of every module built into it, from the module cache.

  go version -m <executable> | go_module_notices.py --module-cache <dir> --goroot <dir> > NOTICES.txt
"""

import argparse
import os
import re
import sys

LICENSE_FILE_RE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|PATENTS)([.-].*)?$", re.IGNORECASE)


def escape(path: str) -> str:
    """Module cache path of a module path or version (upper case letters as `!` + lower case)."""
    return re.sub(r"[A-Z]", lambda match: "!" + match.group(0).lower(), path)


def modules(lines):
    """(path, version) of the modules of `go version -m` output, with replacements applied."""
    result = []
    for line in lines:
        fields = line.strip().split("\t")
        if len(fields) >= 3 and fields[0] == "dep":
            result.append((fields[1], fields[2]))
        elif len(fields) >= 3 and fields[0] == "=>" and result:
            # Replacement of the previous module.
            result[-1] = (fields[1], fields[2])
    return sorted(set(result))


def license_texts(directory: str):
    if not os.path.isdir(directory):
        return []
    texts = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if LICENSE_FILE_RE.match(name) and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                texts.append((name, fh.read().strip()))
    return texts


def section(title: str, texts) -> str:
    text = "=" * 78 + "\n" + title + "\n" + "=" * 78 + "\n\n"
    if not texts:
        return text + "(No license file found in the module.)\n\n"
    return text + "".join("--- {:s} ---\n\n{:s}\n\n".format(name, body) for name, body in texts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module-cache", required=True)
    parser.add_argument("--goroot", required=True)
    parser.add_argument("--title", default="Third-party software")
    args = parser.parse_args()

    found = modules(sys.stdin)
    if not found:
        sys.exit("No modules in the input (expected the output of `go version -m`)")
    output = [
        args.title + "\n\n"
        "This program includes the following third-party software, under their licenses:\n"
        "the Go standard library and {:d} Go modules.\n\n".format(len(found)),
        section("Go standard library (https://go.dev)", license_texts(args.goroot)),
    ]
    missing = []
    for path, version in found:
        texts = license_texts(os.path.join(args.module_cache, escape(path) + "@" + escape(version)))
        if not texts:
            missing.append(path)
        output.append(section("{:s} {:s}".format(path, version), texts))
    sys.stdout.write("".join(output))
    if missing:
        print("warning: no license file for: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
