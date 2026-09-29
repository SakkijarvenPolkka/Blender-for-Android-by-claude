# SPDX-License-Identifier: GPL-2.0-or-later
"""
Package the optional components (`<staging>/<id>/component.json` & `site-packages/`) as the
archives the `android_components` add-on installs, and write the list of components of the
build (`components.json`), published next to the archives in the release of the application.
"""

import argparse
import hashlib
import json
import os
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", required=True, help="Directory with a directory per component")
    parser.add_argument("--build-info", required=True, help="build_info.json of the application")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.build_info, encoding="utf-8") as fh:
        build_info = json.load(fh)
    abi = build_info["abi"]

    os.makedirs(args.output, exist_ok=True)
    components = []
    for component_id in sorted(os.listdir(args.staging)):
        root = os.path.join(args.staging, component_id)
        with open(os.path.join(root, "component.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        meta["abi"] = abi
        filename = "blender-android-{:s}-{:s}.zip".format(meta["id"], abi)
        path = os.path.join(args.output, filename)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr("component.json", json.dumps(meta, indent=2) + "\n")
            for dirpath, dirnames, filenames in os.walk(os.path.join(root, "site-packages")):
                dirnames.sort()
                for name in sorted(filenames):
                    file_path = os.path.join(dirpath, name)
                    archive.write(file_path, os.path.relpath(file_path, root))

        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
        components.append({
            "id": meta["id"],
            "name": meta.get("name", meta["id"]),
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "file": filename,
            "size": os.path.getsize(path),
            "sha256": digest.hexdigest(),
        })
        print("{:s}: {:.1f} MB".format(filename, os.path.getsize(path) / (1024 * 1024)))

    manifest = {
        "abi": abi,
        "blender_version": build_info.get("blender_version", ""),
        "port_revision": build_info.get("port_revision", ""),
        "components": components,
    }
    with open(os.path.join(args.output, "components.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    main()
