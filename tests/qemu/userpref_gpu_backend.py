#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Read or change the GPU back-end stored in Blender's preferences (`userpref.blend`), to test how
Blender loads preferences that select a back-end the build doesn't have: OpenGL is the default of
desktop Blender and was stored by earlier builds of the Android port, which only has Vulkan.

  userpref_gpu_backend.py <userpref.blend>            # print the stored value
  userpref_gpu_backend.py <userpref.blend> <value>    # change it (1: OpenGL, 2: Metal, 8: Vulkan)

Supports uncompressed little-endian blend-files with 8-byte pointers (how Blender writes its
preferences on Android). The offset of `UserDef.gpu_backend` is computed from the file's own DNA.
"""

import re
import struct
import sys

BACKENDS = {1: "OPENGL", 2: "METAL", 8: "VULKAN"}


def blocks(data):
    """(code, data offset, data length) of each block (`BHead`)."""
    if not data.startswith(b"BLENDER"):
        sys.exit("not an uncompressed blend-file")
    if data[7:8] in (b"-", b"_"):
        # Legacy header `BLENDER-v###`: 24 bytes block headers (`SmallBHead8`).
        if data[7:9] != b"-v":
            sys.exit("only little-endian blend-files with 8-byte pointers are supported")
        offset, head_format = 12, "<4siQii"
    else:
        # `BLENDER17-01v####`: 32 bytes block headers (`LargeBHead8`).
        if data[7:13] != b"17-01v":
            sys.exit("unsupported blend-file header: {!r}".format(data[:17]))
        offset, head_format = 17, "<4siQqq"
    head_size = struct.calcsize(head_format)
    while offset + head_size <= len(data):
        fields = struct.unpack_from(head_format, data, offset)
        code = fields[0]
        length = fields[1] if head_format == "<4siQii" else fields[3]
        yield code, offset + head_size, length
        if code == b"ENDB":
            return
        offset += head_size + length
    sys.exit("truncated blend-file")


def strings(data, offset, count):
    result = []
    for _ in range(count):
        end = data.index(b"\0", offset)
        result.append(data[offset:end].decode("utf-8"))
        offset = end + 1
    return result, (offset + 3) & ~3


def member_offset(sdna, struct_name, member_name):
    """Offset and size of a struct member, from an encoded SDNA (`DNA1` block)."""
    def expect(offset, tag):
        if sdna[offset:offset + 4] != tag:
            sys.exit("invalid DNA: no {!r}".format(tag))
        return offset + 4

    offset = expect(expect(0, b"SDNA"), b"NAME")
    (count,) = struct.unpack_from("<i", sdna, offset)
    names, offset = strings(sdna, offset + 4, count)
    offset = expect(offset, b"TYPE")
    (count,) = struct.unpack_from("<i", sdna, offset)
    types, offset = strings(sdna, offset + 4, count)
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
        sys.exit("{:s} has no member {:s}".format(struct_name, member_name))
    sys.exit("no struct {:s} in the DNA".format(struct_name))


def main():
    if len(sys.argv) not in {2, 3}:
        sys.exit(__doc__)
    path = sys.argv[1]
    with open(path, "rb") as fh:
        data = bytearray(fh.read())

    found = {code: (offset, length) for code, offset, length in blocks(data) if code in {b"DNA1", b"USER"}}
    if b"DNA1" not in found or b"USER" not in found:
        sys.exit("{:s}: not a preferences file (no DNA1 or USER block)".format(path))
    dna_offset, dna_length = found[b"DNA1"]
    position, size = member_offset(bytes(data[dna_offset:dna_offset + dna_length]), "UserDef", "gpu_backend")
    if size != 2:
        sys.exit("UserDef.gpu_backend is {:d} bytes, expected a short".format(size))
    user_offset, user_length = found[b"USER"]
    if position + size > user_length:
        sys.exit("USER block too small")

    (value,) = struct.unpack_from("<h", data, user_offset + position)
    print("gpu_backend = {:d} ({:s})".format(value, BACKENDS.get(value, "unknown")))
    if len(sys.argv) == 3:
        new_value = int(sys.argv[2])
        struct.pack_into("<h", data, user_offset + position, new_value)
        with open(path, "wb") as fh:
            fh.write(data)
        print("gpu_backend set to {:d} ({:s})".format(new_value, BACKENDS.get(new_value, "unknown")))


if __name__ == "__main__":
    main()
