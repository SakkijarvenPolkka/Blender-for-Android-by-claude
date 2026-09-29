#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Create a minimal Android root file-system for running Android arm64 executables on a Linux host
with QEMU user-mode emulation (`qemu-aarch64 -L <root> ...`).

Bionic (the dynamic linker `linker64`, `libc.so`, `libm.so`, `libdl.so`) is extracted from an
official Android emulator system image (runtime APEX). Other system libraries (`libandroid.so`,
`libvulkan.so`, `liblog.so`, ...) are the NDK stub libraries: they satisfy the dynamic linker,
Blender doesn't call them in background mode.

Requires `debugfs` (e2fsprogs) and `unzip`.
"""

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

SYSTEM_IMAGE_URL = "https://dl.google.com/android/repository/sys-img/android/arm64-v8a-34_r04.zip"
NDK_STUB_LIBS = (
    "libandroid.so", "libvulkan.so", "liblog.so", "libEGL.so", "libGLESv2.so", "libGLESv3.so",
    "libOpenSLES.so", "libaaudio.so", "libnativewindow.so", "libjnigraphics.so",
)


def gpt_partitions(fh):
    fh.seek(512)
    header = fh.read(92)
    if header[:8] != b"EFI PART":
        raise RuntimeError("Not a GPT disk image")
    entries_lba, entry_count, entry_size = struct.unpack("<QII", header[72:88])
    fh.seek(entries_lba * 512)
    result = {}
    for _ in range(entry_count):
        entry = fh.read(entry_size)
        if entry[:16] == b"\0" * 16:
            continue
        first, last = struct.unpack("<QQ", entry[32:48])
        name = entry[56:128].decode("utf-16le").rstrip("\0")
        result[name] = (first * 512, (last - first + 1) * 512)
    return result


def extract_dynamic_partition(fh, super_offset, name, out_path):
    """Extract a logical partition from an Android "super" partition (LP metadata)."""
    def read(offset, size):
        fh.seek(super_offset + offset)
        return fh.read(size)

    geometry_magic = struct.unpack("<I", read(4096, 4))[0]
    if geometry_magic != 0x616C4467:
        raise RuntimeError("Invalid LP geometry")
    metadata_offset = 4096 * 3
    header = read(metadata_offset, 256)
    magic, _major, _minor, header_size = struct.unpack("<IHHI", header[:12])
    if magic != 0x414C5030:
        raise RuntimeError("Invalid LP metadata")
    tables_size = struct.unpack("<I", header[44:48])[0]
    partitions = struct.unpack("<III", header[80:92])
    extents = struct.unpack("<III", header[92:104])
    tables = read(metadata_offset + header_size, tables_size)

    for i in range(partitions[1]):
        entry = tables[partitions[0] + i * partitions[2]:partitions[0] + (i + 1) * partitions[2]]
        if entry[:36].rstrip(b"\0").decode() != name:
            continue
        _attributes, first_extent, extent_count = struct.unpack("<III", entry[36:48])
        with open(out_path, "wb") as out:
            for j in range(first_extent, first_extent + extent_count):
                extent = tables[extents[0] + j * extents[2]:extents[0] + (j + 1) * extents[2]]
                sectors, _target_type, target_sector, _source = struct.unpack("<QIQI", extent)
                fh.seek(super_offset + target_sector * 512)
                remaining = sectors * 512
                while remaining:
                    chunk = fh.read(min(remaining, 1 << 24))
                    out.write(chunk)
                    remaining -= len(chunk)
        return
    raise RuntimeError("Partition {!r} not found".format(name))


def debugfs(image, command):
    subprocess.run(["debugfs", "-R", command, image], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ndk", required=True, help="Android NDK directory")
    parser.add_argument("--api", default="31")
    parser.add_argument("--system-image-zip", help="Local copy of the system image zip (downloaded otherwise)")
    parser.add_argument("--system-img", help="Already extracted `system.img` (GPT disk image)")
    parser.add_argument("--download-dir", default=None)
    parser.add_argument("output", help="Directory for the root file-system")
    args = parser.parse_args()

    root = os.path.abspath(args.output)
    if os.path.exists(os.path.join(root, "system", "bin", "linker64")):
        print("Android root already prepared:", root)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        image_zip = args.system_image_zip
        if args.system_img:
            pass
        elif image_zip is None:
            download_dir = args.download_dir or tmp
            image_zip = os.path.join(download_dir, os.path.basename(SYSTEM_IMAGE_URL))
            if not os.path.exists(image_zip):
                print("Downloading", SYSTEM_IMAGE_URL, flush=True)
                urllib.request.urlretrieve(SYSTEM_IMAGE_URL, image_zip)

        if args.system_img:
            disk_image = args.system_img
        else:
            print("Extracting system image", flush=True)
            with zipfile.ZipFile(image_zip) as zf:
                member = next(n for n in zf.namelist() if n.endswith("/system.img"))
                disk_image = zf.extract(member, tmp)

        system_raw = os.path.join(tmp, "system.raw")
        with open(disk_image, "rb") as fh:
            parts = gpt_partitions(fh)
            super_offset, _size = parts["super"]
            extract_dynamic_partition(fh, super_offset, "system", system_raw)
        if not args.system_img:
            os.unlink(disk_image)

        apex = os.path.join(tmp, "runtime.apex")
        debugfs(system_raw, "dump /system/apex/com.android.runtime.apex " + apex)
        with zipfile.ZipFile(apex) as zf:
            payload = zf.extract("apex_payload.img", tmp)

        runtime = os.path.join(tmp, "runtime")
        os.makedirs(runtime)
        for directory in ("bin", "lib64"):
            debugfs(payload, "rdump /{:s} {:s}".format(directory, runtime))

        os.makedirs(os.path.join(root, "system", "bin"), exist_ok=True)
        lib_dir = os.path.join(root, "system", "lib64")
        os.makedirs(lib_dir, exist_ok=True)
        shutil.copy2(os.path.join(runtime, "bin", "linker64"), os.path.join(root, "system", "bin"))
        for lib in ("libc.so", "libm.so", "libdl.so", "libdl_android.so"):
            shutil.copy2(os.path.join(runtime, "lib64", "bionic", lib), lib_dir)
        # Provided by the linker itself on recent versions.
        ld_android = os.path.join(runtime, "lib64", "ld-android.so")
        if os.path.isfile(ld_android):
            shutil.copy2(ld_android, lib_dir)

    stub_dir = os.path.join(args.ndk, "toolchains", "llvm", "prebuilt", "linux-x86_64", "sysroot",
                            "usr", "lib", "aarch64-linux-android", args.api)
    for lib in NDK_STUB_LIBS:
        src = os.path.join(stub_dir, lib)
        if os.path.exists(src):
            shutil.copy2(src, lib_dir)

    # Silences the linker warning about the missing generated configuration.
    os.makedirs(os.path.join(root, "linkerconfig"), exist_ok=True)
    open(os.path.join(root, "linkerconfig", "ld.config.txt"), "w").close()
    print("Android root prepared:", root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
