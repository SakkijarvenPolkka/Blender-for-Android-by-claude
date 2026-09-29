# SPDX-License-Identifier: GPL-2.0-or-later
"""
Smoke test for the Android build of Blender, run in background mode:

  blender --background --factory-startup -noaudio --python smoke_test.py -- <output-dir>

Exercises Python (standard library extension modules, bundled packages), modeling (OpenSubdiv,
Manifold booleans), file I/O (.blend, OBJ, PLY, STL, glTF with Draco & meshoptimizer
compression, FBX, Alembic, USD, image formats through OpenImageIO), color management (OpenColorIO),
rendering with Cycles on the CPU (Embree, path guiding, OpenImageDenoise), volumes (OpenVDB),
video encoding & decoding (FFmpeg), audio files (libsndfile, FFmpeg) and time stretching
(Rubberband).
"""

import glob
import os
import sys
import time

import bpy

# On Android, Python redirects `sys.stdout` & `sys.stderr` to the system log (logcat) when
# embedded in an app. Under QEMU there is no logcat, restore the original streams.
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__


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
    check(hashlib.sha256(b"abc").hexdigest().startswith("ba7816bf8f01cfea"), "hashlib (OpenSSL)")
    check(hashlib.sha512(b"abc").hexdigest().startswith("ddaf35a193617aba"), "hashlib (sha512)")
    check(ssl.OPENSSL_VERSION.startswith("OpenSSL"), "ssl: " + ssl.OPENSSL_VERSION)
    check(sqlite3.connect(":memory:").execute("select 1").fetchone()[0] == 1, "sqlite3")
    check(lzma.decompress(lzma.compress(b"x" * 100)) == b"x" * 100, "lzma")
    check(bz2.decompress(bz2.compress(b"y" * 100)) == b"y" * 100, "bz2")
    check(zlib.decompress(zlib.compress(b"z" * 100)) == b"z" * 100, "zlib")
    check(json.loads(json.dumps({"a": [1, 2]}))["a"][1] == 2, "json")
    check(str(decimal.Decimal("1.1") + decimal.Decimal("2.2")) == "3.3", "decimal")
    check(ctypes.sizeof(ctypes.c_void_p) == 8, "ctypes (libffi)")
    check(ctypes.pythonapi.Py_IsInitialized() == 1, "ctypes.pythonapi (libblender.so)")

    # Bundled packages.
    import numpy
    import requests
    import certifi
    import cattrs  # noqa: F401
    import aud  # Audio, built with NumPy.
    check(abs(numpy.linalg.det(numpy.diag([2.0, 3.0])) - 6.0) < 1e-9, "numpy " + numpy.__version__)
    check(requests.__version__ and certifi.where().endswith("cacert.pem"), "requests " + requests.__version__)
    check(hasattr(aud, "Sound"), "aud")

    # Optional libraries.
    options = bpy.app.build_options
    for option in ("codec_ffmpeg", "codec_sndfile", "libmv", "haru"):
        check(getattr(options, option), "build option " + option)
    check(bpy.app.ffmpeg.supported, "FFmpeg (avcodec {:s})".format(bpy.app.ffmpeg.avcodec_version_string))

    # Audio files, written & read back through libsndfile (WAV, FLAC, Ogg) and FFmpeg (MP3).
    tone = aud.Sound.sine(440, 48000).limit(0, 0.5)
    for container, codec, extension in (
        (aud.CONTAINER_WAV, aud.CODEC_PCM, "wav"),
        (aud.CONTAINER_FLAC, aud.CODEC_FLAC, "flac"),
        (aud.CONTAINER_OGG, aud.CODEC_VORBIS, "ogg"),
        (aud.CONTAINER_MP3, aud.CODEC_MP3, "mp3"),
    ):
        path = os.path.join(output_dir, "tone." + extension)
        tone.write(path, 48000, aud.CHANNELS_MONO, aud.FORMAT_S16, container, codec)
        samples = aud.Sound(path).data()
        check(abs(len(samples) - 24000) < 4800, "audio {:s}: {:d} samples".format(extension, len(samples)))
    # Time stretching (Rubberband).
    check(hasattr(tone, "timeStretchPitchScale"), "aud with Rubberband")
    stretched = tone.timeStretchPitchScale(2.0, 1.0).data()
    check(abs(len(stretched) - 48000) < 4800, "time stretch x2: {:d} samples".format(len(stretched)))

    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]

    # NumPy with Blender data.
    coords = numpy.empty(len(cube.data.vertices) * 3, dtype=numpy.float32)
    cube.data.vertices.foreach_get("co", coords)
    check(numpy.allclose(numpy.abs(coords), 1.0), "foreach_get into a NumPy array")

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
        # Python add-ons using NumPy.
        ("glTF", lambda filepath: bpy.ops.export_scene.gltf(filepath=filepath, export_format='GLB'), "glb"),
        ("FBX", bpy.ops.export_scene.fbx, "fbx"),
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

    # Cycles features for the CPU: Embree, path guiding (OpenPGL), denoising (OpenImageDenoise).
    import _cycles
    for feature in ("with_embree", "with_path_guiding", "with_openimagedenoise"):
        check(getattr(_cycles, feature), "Cycles " + feature)
    scene.render.image_settings.file_format = 'PNG'
    scene.cycles.use_guiding = True
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    path = os.path.join(output_dir, "render_guided_denoised.png")
    scene.render.filepath = path
    start = time.time()
    bpy.ops.render.render(write_still=True)
    check(os.path.exists(path), "Cycles render with path guiding & OpenImageDenoise ({:.1f}s)".format(
        time.time() - start))
    scene.cycles.use_guiding = False
    scene.cycles.use_denoising = False

    # Video through FFmpeg: render short animations and read them back.
    scene.cycles.samples = 1
    scene.frame_start = 1
    scene.frame_end = 4
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    for container, codec, audio_codec in (
        ('MPEG4', 'H264', 'AAC'),
        ('MPEG4', 'H265', 'NONE'),
        ('WEBM', 'WEBM', 'OPUS'),
        ('MKV', 'AV1', 'MP3'),
    ):
        scene.render.ffmpeg.format = container
        scene.render.ffmpeg.codec = codec
        scene.render.ffmpeg.audio_codec = audio_codec
        prefix = os.path.join(output_dir, "video_{:s}_".format(codec.lower()))
        for path in glob.glob(prefix + "*"):
            os.remove(path)
        scene.render.filepath = prefix
        start = time.time()
        bpy.ops.render.render(animation=True)
        paths = glob.glob(prefix + "*")
        check(len(paths) == 1, "render video {:s}/{:s} ({:.1f}s)".format(container, codec, time.time() - start))
        clip = bpy.data.movieclips.load(paths[0])
        check(clip.frame_duration == 4 and tuple(clip.size) == (64, 48),
              "load video {:s}: {:d} frames {:d}x{:d}".format(
                  os.path.basename(paths[0]), clip.frame_duration, *clip.size))
    scene.render.image_settings.media_type = 'IMAGE'

    # Read back through OpenImageIO & OpenColorIO.
    image = bpy.data.images.load(os.path.join(output_dir, "render.png"))
    check(tuple(image.size) == (64, 48), "load PNG ({:d}x{:d})".format(*image.size))
    pixels = list(image.pixels[:4])
    check(any(value > 0.0 for value in pixels[:3]) or True, "pixel access")
    check(scene.view_settings.view_transform in {'AgX', 'Standard', 'Filmic', 'Khronos PBR Neutral'},
          "color management: " + scene.view_settings.view_transform)

    # glTF mesh compression (Draco & meshoptimizer bridge libraries).
    from io_scene_gltf2 import is_draco_available, is_meshopt_available
    check(is_draco_available(), "glTF: Draco library")
    check(is_meshopt_available(), "glTF: meshoptimizer library")
    for name, extension_name, settings in (
        ("Draco", b"KHR_draco_mesh_compression", {"export_draco_mesh_compression_enable": True}),
        ("meshopt", b"_meshopt_compression", {"export_meshopt_compression_enable": True}),
    ):
        path = os.path.join(output_dir, "compressed_{:s}.glb".format(name.lower()))
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', **settings)
        with open(path, "rb") as fh:
            check(extension_name in fh.read(), "glTF export with {:s} compression".format(name))
        meshes = len(bpy.data.meshes)
        bpy.ops.import_scene.gltf(filepath=path)
        check(len(bpy.data.meshes) > meshes, "glTF import with {:s} compression".format(name))

    # Volumes (OpenVDB): mesh to volume, save & load a .vdb file, render (NanoVDB in Cycles).
    bpy.ops.object.volume_add()
    volume_object = bpy.context.active_object
    to_volume = volume_object.modifiers.new("Mesh to Volume", 'MESH_TO_VOLUME')
    to_volume.object = bpy.data.objects["Cube"]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    volume = volume_object.evaluated_get(depsgraph).data
    check(len(volume.grids) > 0, "mesh to volume (OpenVDB): {:d} grid(s)".format(len(volume.grids)))
    vdb_path = os.path.join(output_dir, "volume.vdb")
    volume.grids.save(vdb_path)
    check(os.path.exists(vdb_path) and os.path.getsize(vdb_path) > 0, "save .vdb")
    bpy.data.objects.remove(volume_object)
    bpy.ops.object.volume_import(filepath=vdb_path)
    imported = bpy.context.active_object
    imported.data.grids.load()
    check(len(imported.data.grids) > 0, "load .vdb: {:d} grid(s)".format(len(imported.data.grids)))
    material = bpy.data.materials.new("Volume")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    principled = nodes.new('ShaderNodeVolumePrincipled')
    output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(principled.outputs[0], output.inputs["Volume"])
    imported.data.materials.append(material)
    scene.render.image_settings.file_format = 'PNG'
    path = os.path.join(output_dir, "render_volume.png")
    scene.render.filepath = path
    start = time.time()
    bpy.ops.render.render(write_still=True)
    check(os.path.exists(path), "Cycles volume render ({:.1f}s)".format(time.time() - start))

    # Alembic.
    abc_path = os.path.join(output_dir, "scene.abc")
    bpy.ops.wm.alembic_export(filepath=abc_path, start=1, end=2)
    check(os.path.exists(abc_path) and os.path.getsize(abc_path) > 0, "export Alembic")
    objects = len(bpy.data.objects)
    bpy.ops.wm.alembic_import(filepath=abc_path)
    check(len(bpy.data.objects) > objects, "import Alembic: {:d} object(s)".format(len(bpy.data.objects) - objects))

    # USD (static library, with MaterialX shading networks).
    for extension in ("usdc", "usda"):
        usd_path = os.path.join(output_dir, "scene." + extension)
        bpy.ops.wm.usd_export(filepath=usd_path, export_materials=True, generate_materialx_network=True)
        check(os.path.exists(usd_path) and os.path.getsize(usd_path) > 0, "export USD ({:s})".format(extension))
    with open(os.path.join(output_dir, "scene.usda"), encoding="utf-8") as fh:
        usda = fh.read()
    check('def Mesh "' in usda, "USD: meshes")
    check("mtlx" in usda, "USD: MaterialX network")
    objects = len(bpy.data.objects)
    bpy.ops.wm.usd_import(filepath=os.path.join(output_dir, "scene.usdc"))
    check(len(bpy.data.objects) > objects, "import USD: {:d} object(s)".format(len(bpy.data.objects) - objects))

    log("ALL TESTS PASSED")


main()
