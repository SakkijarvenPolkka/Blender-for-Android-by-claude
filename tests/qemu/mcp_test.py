# SPDX-License-Identifier: GPL-2.0-or-later
"""
End-to-end test of Blender's MCP server (the `mcp_server` add-on), as an MCP client such as
Claude Code uses it:

  mcp_test.py <url> <token> <output-dir>

Runs on the build machine against Blender running in background mode (see `run_blender.sh`).
"""

import base64
import json
import os
import sys
import time
import urllib.request

URL, TOKEN, OUT = sys.argv[1:4]
VERSION = "2026-07-28"
_request_id = 0
_failures = []


def rpc(method, params=None, *, modern=True, name=None):
    global _request_id
    _request_id += 1
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer " + TOKEN,
    }
    params = dict(params or {})
    if modern:
        headers.update({"MCP-Protocol-Version": VERSION, "Mcp-Method": method})
        if name:
            headers["Mcp-Name"] = name
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "mcp_test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    body = json.dumps({"jsonrpc": "2.0", "id": _request_id, "method": method, "params": params}).encode()
    request = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read())


def check(condition, message):
    print(("ok: " if condition else "FAILED: ") + message, flush=True)
    if not condition:
        _failures.append(message)


def call(tool, **arguments):
    start = time.time()
    result = rpc("tools/call", {"name": tool, "arguments": arguments}, name=tool)["result"]
    text = "\n".join(c["text"] for c in result["content"] if c["type"] == "text")
    images = [c for c in result["content"] if c["type"] == "image"]
    print("[{:s} {:.1f}s{:s}] {:s}".format(
        tool, time.time() - start, " error" if result["isError"] else "", text[:300].replace("\n", " ")))
    for i, image in enumerate(images):
        with open(os.path.join(OUT, "mcp_{:s}_{:d}.png".format(tool, i)), "wb") as fh:
            fh.write(base64.b64decode(image["data"]))
    return result, text, images


def main():
    os.makedirs(OUT, exist_ok=True)

    discover = rpc("server/discover")["result"]
    check(VERSION in discover["supportedVersions"], "server/discover")
    tools = [tool["name"] for tool in rpc("tools/list")["result"]["tools"]]
    check("execute_python" in tools and "render_image" in tools, "tools/list: " + ", ".join(tools))
    legacy = rpc("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "legacy", "version": "1"},
    }, modern=False)
    check(legacy["result"]["protocolVersion"] == "2025-06-18", "legacy initialize (2025-06-18)")

    result, text, _ = call("execute_python", code="""
import numpy as np
for obj in list(bpy.data.objects):
    if obj.type == 'MESH':
        bpy.data.objects.remove(obj)
n = 24
xs, ys = np.meshgrid(np.linspace(-2, 2, n), np.linspace(-2, 2, n))
zs = 0.3 * np.sin(xs * 3) * np.cos(ys * 3)
verts = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
faces = [(i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j)
         for i in range(n - 1) for j in range(n - 1)]
mesh = bpy.data.meshes.new("Wave")
mesh.from_pydata(verts.tolist(), [], faces)
obj = bpy.data.objects.new("Wave", mesh)
bpy.context.scene.collection.objects.link(obj)
material = bpy.data.materials.new("Orange")
material.use_nodes = True
material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1.0, 0.35, 0.05, 1.0)
obj.data.materials.append(material)
obj.modifiers.new("Subdivision", 'SUBSURF').levels = 1
print("vertices", len(mesh.vertices))
result = obj.name
""")
    check(not result["isError"] and "result = 'Wave'" in text, "execute_python (NumPy mesh)")
    result, text, _ = call("execute_python", code="print(obj.name, round(np.pi, 3))")
    check(not result["isError"] and "Wave 3.142" in text, "execute_python keeps variables")
    result, text, _ = call("execute_python", code="1 / 0")
    check(result["isError"] and "ZeroDivisionError" in text, "execute_python reports errors")
    result, text, _ = call("get_scene_info")
    check(not result["isError"] and "\"Wave\"" in text, "get_scene_info")
    result, text, _ = call("get_object_info", name="Wave")
    check(not result["isError"] and "mesh_evaluated" in text, "get_object_info")
    result, _, _ = call("get_viewport_screenshot")
    check(result["isError"], "get_viewport_screenshot unavailable in background mode")
    result, _, images = call("render_image", width=160, height=120, samples=4, engine="CYCLES")
    check(not result["isError"] and images and images[0]["mimeType"] == "image/png", "render_image (Cycles)")
    blend = os.path.join(OUT, "mcp_test.blend")
    result, _, _ = call("save_blend_file", filepath=blend)
    check(not result["isError"] and os.path.getsize(blend) > 10000, "save_blend_file")

    if _failures:
        print("MCP TEST FAILED")
        return 1
    print("MCP TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
