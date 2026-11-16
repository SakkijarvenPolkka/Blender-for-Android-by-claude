#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Read or change the GPU back-end stored in Blender's preferences (`userpref.blend`), to test how
Blender loads preferences that select a back-end the build doesn't have: OpenGL is the default of
desktop Blender and was stored by earlier builds of the Android port, which only has Vulkan.

  userpref_gpu_backend.py <userpref.blend>                       # print the stored value
  userpref_gpu_backend.py <userpref.blend> <value>               # change it (1: OpenGL, 2: Metal, 8: Vulkan)
  userpref_gpu_backend.py <userpref.blend> <value> --version 304 # also mark the file as written by 3.4
  userpref_gpu_backend.py <userpref.blend> --expect 8 [...]      # fail unless the stored value is 8

Also usable as a module (`read_gpu_backend()`, `write_gpu_backend()`, `set_file_version()`), e.g.
from Blender's Python. Supports uncompressed little-endian blend-files with 8-byte pointers (how
Blender writes its preferences on Android). The offset of `UserDef.gpu_backend` is computed from the
file's own DNA.
"""

import re
import struct
import sys

BACKENDS = {0: "NONE", 1: "OPENGL", 2: "METAL", 8: "VULKAN"}


class BlendFileError(Exception):
    pass


def _header(data):
    """(block header format, offset of the first block, slice of the version digits)."""
    if not data.startswith(b"BLENDER"):
        raise BlendFileError("not an uncompressed blend-file")
    if data[7:8] in (b"-", b"_"):
        # Legacy header `BLENDER-v###`: 24 bytes block headers (`SmallBHead8`).
        if data[7:9] != b"-v":
            raise BlendFileError("only little-endian blend-files with 8-byte pointers are supported")
        return "<4siQii", 12, slice(9, 12)
    # `BLENDER17-01v####`: 32 bytes block headers (`LargeBHead8`).
    if data[7:13] != b"17-01v":
        raise BlendFileError("unsupported blend-file header: {!r}".format(bytes(data[:17])))
    return "<4siQqq", 17, slice(13, 17)


def _blocks(data):
    """(code, data offset, data length) of each block (`BHead`)."""
    head_format, offset, _ = _header(data)
    head_size = struct.calcsize(head_format)
    while offset + head_size <= len(data):
        fields = struct.unpack_from(head_format, data, offset)
        code = fields[0]
        length = fields[1] if head_size == 24 else fields[3]
        yield code, offset + head_size, length
        if code == b"ENDB":
            return
        offset += head_size + length
    raise BlendFileError("truncated blend-file")


def _strings(data, offset, count):
    result = []
    for _ in range(count):
        end = data.index(b"\0", offset)
        result.append(data[offset:end].decode("utf-8"))
        offset = end + 1
    return result, (offset + 3) & ~3


def _member_offset(sdna, struct_name, member_name):
    """Offset and size of a struct member, from an encoded SDNA (`DNA1` block)."""
    def expect(offset, tag):
        if sdna[offset:offset + 4] != tag:
            raise BlendFileError("invalid DNA: no {!r}".format(tag))
        return offset + 4

    offset = expect(expect(0, b"SDNA"), b"NAME")
    (count,) = struct.unpack_from("<i", sdna, offset)
    names, offset = _strings(sdna, offset + 4, count)
    offset = expect(offset, b"TYPE")
    (count,) = struct.unpack_from("<i", sdna, offset)
    types, offset = _strings(sdna, offset + 4, count)
    offset = expect(offset, b"TLEN")
    sizes = struct.unpack_from("<{:d}H".format(len(types)), sdna, offset)
    offset = expect((offset + 2 * len(types) + 3) & ~3, b"STRC")
    (count,) = struct.unpack_from("<i", sdna, offset)
    offset += 4
    for _ in range(count):
        type_index, members_num = struct.unpack_from("<hh", sdna, offset)
        members = struct.unpack_from("<{:d}h".format(2 * members_num), sdna, offset + 4)
        offset += 4 + 4 * members_num
        if types[type_index] != struct_name:
            continue
        position = 0
        for member_type, member_name_index in zip(members[0::2], members[1::2]):
            name = names[member_name_index]
            # Like `DNA_struct_member_size()`: pointers and arrays (all dimensions).
            array_num = 1
            for dimension in re.findall(r"\[(\d+)\]", name):
                array_num *= int(dimension)
            is_pointer = name.startswith("*") or name.startswith("(*")
            size = (8 if is_pointer else sizes[member_type]) * array_num
            if name == member_name:
                return position, size
            position += size
        raise BlendFileError("{:s} has no member {:s}".format(struct_name, member_name))
    raise BlendFileError("no struct {:s} in the DNA".format(struct_name))


def _gpu_backend_offset(data):
    found = {code: (offset, length) for code, offset, length in _blocks(data) if code in {b"DNA1", b"USER"}}
    if b"DNA1" not in found or b"USER" not in found:
        raise BlendFileError("not a preferences file (no DNA1 or USER block)")
    dna_offset, dna_length = found[b"DNA1"]
    position, size = _member_offset(bytes(data[dna_offset:dna_offset + dna_length]), "UserDef", "gpu_backend")
    if size != 2:
        raise BlendFileError("UserDef.gpu_backend is {:d} bytes, expected a short".format(size))
    user_offset, user_length = found[b"USER"]
    if position + size > user_length:
        raise BlendFileError("USER block too small")
    return user_offset + position


def _read(path):
    with open(path, "rb") as fh:
        return bytearray(fh.read())


def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def read_gpu_backend(path):
    data = _read(path)
    return struct.unpack_from("<h", data, _gpu_backend_offset(data))[0]


def write_gpu_backend(path, value):
    data = _read(path)
    struct.pack_into("<h", data, _gpu_backend_offset(data), value)
    _write(path, data)


def set_file_version(path, version):
    """Mark the file as written by another Blender version (e.g. 304 for 3.4): versioning runs."""
    data = _read(path)
    digits = _header(data)[2]
    text = "{:0{:d}d}".format(version, digits.stop - digits.start).encode("ascii")
    if len(text) != digits.stop - digits.start:
        raise BlendFileError("version {:d} doesn't fit the header".format(version))
    data[digits] = text
    _write(path, data)


def main():
    args = sys.argv[1:]
    options = {}
    for option in ("--version", "--expect"):
        if option in args:
            index = args.index(option)
            options[option] = int(args[index + 1])
            del args[index:index + 2]
    if len(args) not in {1, 2}:
        sys.exit(__doc__)
    path = args[0]
    try:
        value = read_gpu_backend(path)
        print("gpu_backend = {:d} ({:s})".format(value, BACKENDS.get(value, "unknown")))
        # E.g. the value Blender saved: otherwise the offset is wrong (changes would go elsewhere).
        if "--expect" in options and value != options["--expect"]:
            sys.exit("{:s}: gpu_backend is {:d}, expected {:d}".format(path, value, options["--expect"]))
        if len(args) == 2:
            value = int(args[1])
            write_gpu_backend(path, value)
            print("gpu_backend set to {:d} ({:s})".format(value, BACKENDS.get(value, "unknown")))
        if "--version" in options:
            set_file_version(path, options["--version"])
            print("file version set to {:d}".format(options["--version"]))
    except (OSError, BlendFileError) as ex:
        sys.exit("{:s}: {!s}".format(path, ex))


if __name__ == "__main__":
    main()
