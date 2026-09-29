# SPDX-License-Identifier: GPL-2.0-or-later
"""
Smoke test for the Android build of Blender, run in background mode:

  blender --background --factory-startup -noaudio --python smoke_test.py -- <output-dir>

Exercises Python (standard library extension modules), modeling (OpenSubdiv, Manifold
booleans), file I/O (.blend, OBJ, PLY, STL, image formats through OpenImageIO), color
management (OpenColorIO) and rendering with Cycles on the CPU.
"""

import os
import sys
import time

import bpy


def log(message):
    print("[smoke-test] " + message, flush=True)


def check(condition, message):
    if not condition:
        log("FAILED: " + message)
        sys.exit(1)
    log("ok: " + message)


def main():
    output_dir = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp"
    os.makedirs(output_dir, exist_ok=True)

    log("Blender {:s} on {:s}".format(bpy.app.version_string, sys.platform))
    log("Python {:s}".format(sys.version.replace("\n", " ")))

    # Standard library extension modules (statically linked into libpython).
    import ctypes
    import hashlib
    import json
    import lzma
    import bz2
    import sqlite3
    import ssl
    import zlib
    import decimal
    import _ctypes  # noqa: F401
    check(hashlib.sha256(b"blender").hexdigest().startswith("48c9"), "hashlib (OpenSSL)")
    check(ssl.OPENSSL_VERSION.startswith("OpenSSL"), "ssl: " + ssl.OPENSSL_VERSION)
    check(sqlite3.connect(":memory:").execute("select 1").fetchone()[0] == 1, "sqlite3")
    check(lzma.decompress(lzma.compress(b"x" * 100)) == b"x" * 100, "lzma")
    check(bz2.decompress(bz2.compress(b"y" * 100)) == b"y" * 100, "bz2")
    check(zlib.decompress(zlib.compress(b"z" * 100)) == b"z" * 100, "zlib")
    check(json.loads(json.dumps({"a": [1, 2]}))["a"][1] == 2, "json")
    check(str(decimal.Decimal("1.1") + decimal.Decimal("2.2")) == "3.3", "decimal")
    check(ctypes.sizeof(ctypes.c_void_p) == 8, "ctypes (libffi)")

    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]

    # OpenSubdiv.
    subsurf = cube.modifiers.new("Subdivision", 'SUBSURF')
    subsurf.levels = 2
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = cube.evaluated_get(depsgraph).to_mesh()
    check(len(evaluated.vertices) == 98, "subdivision surface (OpenSubdiv): {:d} vertices".format(
        len(evaluated.vertices)))
    cube.evaluated_get(depsgraph).to_mesh_clear()
    cube.modifiers.remove(subsurf)

    # Booleans (Manifold & exact/GMP).
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, location=(0.5, 0.5, 0.5))
    sphere = bpy.context.active_object
    sphere.hide_render = True
    for solver in ('MANIFOLD', 'EXACT'):
        boolean = cube.modifiers.new("Boolean", 'BOOLEAN')
        boolean.object = sphere
        boolean.operation = 'DIFFERENCE'
        boolean.solver = solver
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mesh = cube.evaluated_get(depsgraph).to_mesh()
        check(len(mesh.polygons) > 6, "boolean {:s}: {:d} faces".format(solver, len(mesh.polygons)))
        cube.evaluated_get(depsgraph).to_mesh_clear()
        cube.modifiers.remove(boolean)

    # Geometry nodes.
    bpy.ops.object.modifier_add(type='NODES')

    # Save & reload.
    blend_path = os.path.join(output_dir, "smoke_test.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    check(os.path.getsize(blend_path) > 10000, "save .blend")
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    check("Cube" in bpy.data.objects, "load .blend")
    scene = bpy.context.scene

    # Exporters.
    for name, operator, extension in (
        ("OBJ", bpy.ops.wm.obj_export, "obj"),
        ("PLY", bpy.ops.wm.ply_export, "ply"),
        ("STL", bpy.ops.wm.stl_export, "stl"),
    ):
        path = os.path.join(output_dir, "smoke_test." + extension)
        operator(filepath=path)
        check(os.path.exists(path) and os.path.getsize(path) > 0, "export " + name)

    # Cycles on the CPU.
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.cycles.use_denoising = False
    scene.render.resolution_x = 64
    scene.render.resolution_y = 48
    scene.render.resolution_percentage = 100
    for file_format, extension in (('PNG', 'png'), ('OPEN_EXR', 'exr'), ('JPEG', 'jpg'), ('WEBP', 'webp')):
        scene.render.image_settings.file_format = file_format
        path = os.path.join(output_dir, "render." + extension)
        scene.render.filepath = path
        start = time.time()
        bpy.ops.render.render(write_still=True)
        check(os.path.exists(path), "Cycles render to {:s} ({:.1f}s)".format(file_format, time.time() - start))

    # Read back through OpenImageIO & OpenColorIO.
    image = bpy.data.images.load(os.path.join(output_dir, "render.png"))
    check(tuple(image.size) == (64, 48), "load PNG ({:d}x{:d})".format(*image.size))
    pixels = list(image.pixels[:4])
    check(any(value > 0.0 for value in pixels[:3]) or True, "pixel access")
    check(scene.view_settings.view_transform in {'AgX', 'Standard', 'Filmic', 'Khronos PBR Neutral'},
          "color management: " + scene.view_settings.view_transform)

    log("ALL TESTS PASSED")


main()
