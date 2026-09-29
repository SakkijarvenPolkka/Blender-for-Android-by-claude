# SPDX-License-Identifier: GPL-2.0-or-later
"""
Copy the files a CMake project would install below a prefix, without building or installing
the rest of the project (e.g. only USD's Python modules): reads the `file(INSTALL ...)` rules of
the `cmake_install.cmake` scripts of a build directory.

Compiled Python files (`.pyc`) are skipped (Python writes its own cache), shared libraries are
stripped.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([^\s()"]+)')
PREFIX = "${CMAKE_INSTALL_PREFIX}/"
KEYWORDS = {"DESTINATION", "TYPE", "FILES", "RENAME", "PERMISSIONS", "OPTIONAL",
            "USE_SOURCE_PERMISSIONS", "FILES_MATCHING", "MESSAGE_NEVER", "MESSAGE_LAZY"}


def install_rules(build_dir):
    for root, _dirs, files in os.walk(build_dir):
        if "cmake_install.cmake" not in files:
            continue
        with open(os.path.join(root, "cmake_install.cmake"), encoding="utf-8") as fh:
            text = fh.read()
        for match in re.finditer(r"file\(INSTALL\s(.*?)\)\s*$", text, re.MULTILINE | re.DOTALL):
            tokens = [token.group(1) if token.group(1) is not None else token.group(2)
                      for token in TOKEN_RE.finditer(match.group(1))]
            rule = {"files": [], "optional": False, "rename": None}
            key = None
            for token in tokens:
                if token in KEYWORDS:
                    key = token
                    if token == "OPTIONAL":
                        rule["optional"] = True
                    continue
                if key == "DESTINATION":
                    rule["destination"] = token
                elif key == "TYPE":
                    rule["type"] = token
                elif key == "RENAME":
                    rule["rename"] = token
                elif key == "FILES":
                    rule["files"].append(token)
            if "destination" in rule:
                yield rule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--prefix", required=True, help="Install prefix to copy, e.g. lib/python/pxr")
    parser.add_argument("--output", required=True)
    parser.add_argument("--strip", help="Strip tool for shared libraries")
    parser.add_argument("--exclude", action="append", default=[],
                        help="Skip destinations containing this directory name (e.g. testenv)")
    parser.add_argument("--append", action="append", default=[], metavar="SOURCE=FILE",
                        help="Append the contents of SOURCE to an installed FILE (relative to the output)")
    args = parser.parse_args()

    prefix = PREFIX + args.prefix.strip("/")
    count = 0
    for rule in install_rules(args.build_dir):
        destination = rule["destination"]
        if destination != prefix and not destination.startswith(prefix + "/"):
            continue
        relative = destination[len(prefix):].lstrip("/")
        if any(name in relative.split("/") for name in args.exclude):
            continue
        target_dir = os.path.join(args.output, relative)
        for source in rule["files"]:
            if source.endswith(".pyc"):
                continue
            if not os.path.exists(source):
                if rule["optional"]:
                    continue
                sys.exit("Missing file (not built?): " + source)
            target = os.path.join(target_dir, rule["rename"] or os.path.basename(source))
            os.makedirs(target_dir, exist_ok=True)
            if rule.get("type") == "DIRECTORY":
                shutil.copytree(source, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
            else:
                shutil.copy2(source, target)
                if args.strip and rule.get("type") in {"SHARED_LIBRARY", "MODULE"}:
                    subprocess.check_call([args.strip, "--strip-unneeded", target])
            count += 1
    if not count:
        sys.exit("Nothing to install below " + prefix)
    for item in args.append:
        source, target = item.split("=", 1)
        with open(source, encoding="utf-8") as src, \
                open(os.path.join(args.output, target), "a", encoding="utf-8") as dst:
            dst.write(src.read())
    print("Installed {:d} files to {:s}".format(count, args.output))


if __name__ == "__main__":
    main()
