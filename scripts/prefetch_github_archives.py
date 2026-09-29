#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Fallback for networks where GitHub source archives (``/archive/...tar.gz`` and
``codeload.github.com``) are not reachable but ``git clone`` is.

For every dependency whose download URL is a GitHub source archive and whose
archive is not yet in the download directory, the repository is cloned at the
required tag/commit and packed with ``git archive``. The resulting files are
listed in ``<download-dir>/unverified.txt``: the dependency superbuild accepts
them without checking the checksum from ``versions.cmake`` (``git archive``
output is not byte-identical to GitHub's archives).

Normal builds (and CI) do not need this script.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Dependencies used by `deps/CMakeLists.txt` (prefixes in Blender's `versions.cmake`).
PREFIXES = (
    "BROTLI DEFLATE JPEG OPENJPEG OPENJPH IMATH OPENEXR FMT ROBINMAP PUGIXML TBB "
    "SSE2NEON EXPAT YAMLCPP PYSTRING MINIZIPNG OPENCOLORIO OPENIMAGEIO OPENSUBDIV MANIFOLD "
    "VULKAN_HEADERS SPIRV_HEADERS SPIRV_TOOLS SHADERC_GLSLANG SHADERC"
).split()

GITHUB_ARCHIVE_RE = re.compile(
    r"^https://(?:github\.com/(?P<org>[^/]+)/(?P<repo>[^/]+)/archive/(?:refs/tags/)?(?P<ref>.+)\.tar\.gz"
    r"|codeload\.github\.com/(?P<org2>[^/]+)/(?P<repo2>[^/]+)/tar\.gz/(?:refs/tags/)?(?P<ref2>.+))$"
)


def read_versions(versions_cmake):
    script = "include({:s})\n".format(versions_cmake.replace("\\", "/"))
    for prefix in PREFIXES:
        script += 'message("{0}|${{{0}_URI}}|${{{0}_FILE}}")\n'.format(prefix)
    with tempfile.NamedTemporaryFile("w", suffix=".cmake", delete=False) as fh:
        fh.write(script)
        script_path = fh.name
    try:
        out = subprocess.run(["cmake", "-P", script_path], check=True, capture_output=True, text=True)
    finally:
        os.unlink(script_path)
    result = []
    for line in out.stderr.splitlines():
        prefix, uri, filename = line.split("|")
        result.append((prefix, uri, filename))
    return result


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch(org, repo, ref, dst_file):
    url = "https://github.com/{:s}/{:s}.git".format(org, repo)
    with tempfile.TemporaryDirectory() as tmp:
        checkout = os.path.join(tmp, repo)
        os.makedirs(checkout)
        git("init", "-q", cwd=checkout)
        git("remote", "add", "origin", url, cwd=checkout)
        # Works for tags, branches and commit hashes alike.
        try:
            git("fetch", "-q", "--depth", "1", "origin", "refs/tags/{:s}".format(ref), cwd=checkout)
        except subprocess.CalledProcessError:
            git("fetch", "-q", "--depth", "1", "origin", ref, cwd=checkout)
        git("checkout", "-q", "FETCH_HEAD", cwd=checkout)
        prefix = "{:s}-{:s}/".format(repo, ref.lstrip("v"))
        tmp_file = dst_file + ".tmp"
        with open(tmp_file, "wb") as fh:
            subprocess.run(
                ["git", "archive", "--format=tar.gz", "--prefix=" + prefix, "HEAD"],
                cwd=checkout, check=True, stdout=fh,
            )
        os.replace(tmp_file, dst_file)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blender-source", required=True)
    parser.add_argument("--download-dir", required=True)
    args = parser.parse_args()

    versions_cmake = os.path.join(args.blender_source, "build_files", "build_environment", "cmake", "versions.cmake")
    os.makedirs(args.download_dir, exist_ok=True)
    unverified_path = os.path.join(args.download_dir, "unverified.txt")
    unverified = set()
    if os.path.exists(unverified_path):
        with open(unverified_path) as fh:
            unverified = {line.strip() for line in fh if line.strip()}

    for prefix, uri, filename in read_versions(versions_cmake):
        match = GITHUB_ARCHIVE_RE.match(uri)
        if not match:
            continue
        dst = os.path.join(args.download_dir, filename)
        # Failed downloads can leave empty files behind.
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            continue
        org = match.group("org") or match.group("org2")
        repo = match.group("repo") or match.group("repo2")
        ref = match.group("ref") or match.group("ref2")
        print("Fetching {:s} ({:s}/{:s} @ {:s}) with git".format(prefix, org, repo, ref), flush=True)
        fetch(org, repo, ref, dst)
        unverified.add(filename)

    with open(unverified_path, "w") as fh:
        fh.write("\n".join(sorted(unverified)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
