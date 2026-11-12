"""Genera un maniquí VRM mínimo (cajas sobre un esqueleto humanoide) para probar el avatar sin el modelo real.

    .venv\\Scripts\\python.exe scripts\\maniqui_vrm.py salida.vrm [--v0]

Brazo izquierdo del personaje en rojo, derecho en azul y una «nariz» amarilla al frente de la cabeza,
para comprobar a simple vista hacia dónde mira y qué brazo se mueve. --v0 lo exporta como VRM 0.x (mira a -Z).
"""
import json
import struct
import sys

# hueso: (padre, posición en el mundo en pose T, mirando a +Z, izquierda = +X)
SKELETON = {
    "hips": (None, (0, 0.95, 0)), "spine": ("hips", (0, 1.05, 0)), "chest": ("spine", (0, 1.18, 0)),
    "neck": ("chest", (0, 1.38, 0)), "head": ("neck", (0, 1.46, 0)),
    "leftShoulder": ("chest", (0.05, 1.34, 0)), "leftUpperArm": ("leftShoulder", (0.17, 1.34, 0)),
    "leftLowerArm": ("leftUpperArm", (0.43, 1.34, 0)), "leftHand": ("leftLowerArm", (0.67, 1.34, 0)),
    "rightShoulder": ("chest", (-0.05, 1.34, 0)), "rightUpperArm": ("rightShoulder", (-0.17, 1.34, 0)),
    "rightLowerArm": ("rightUpperArm", (-0.43, 1.34, 0)), "rightHand": ("rightLowerArm", (-0.67, 1.34, 0)),
    "leftUpperLeg": ("hips", (0.09, 0.9, 0)), "leftLowerLeg": ("leftUpperLeg", (0.09, 0.5, 0)),
    "leftFoot": ("leftLowerLeg", (0.09, 0.08, 0)),
    "rightUpperLeg": ("hips", (-0.09, 0.9, 0)), "rightLowerLeg": ("rightUpperLeg", (-0.09, 0.5, 0)),
    "rightFoot": ("rightLowerLeg", (-0.09, 0.08, 0)),
}
# caja de cada hueso: (centro relativo al hueso, tamaño, material)
BOXES = {
    "hips": ((0, 0, 0), (0.26, 0.14, 0.14), 0), "spine": ((0, 0.065, 0), (0.22, 0.13, 0.13), 0),
    "chest": ((0, 0.1, 0), (0.28, 0.2, 0.15), 0), "neck": ((0, 0.04, 0), (0.06, 0.08, 0.06), 0),
    "head": ((0, 0.1, 0), (0.17, 0.2, 0.18), 0),
    "leftUpperArm": ((0.13, 0, 0), (0.26, 0.07, 0.07), 1), "leftLowerArm": ((0.12, 0, 0), (0.24, 0.06, 0.06), 1),
    "leftHand": ((0.05, 0, 0), (0.1, 0.03, 0.08), 1),
    "rightUpperArm": ((-0.13, 0, 0), (0.26, 0.07, 0.07), 2), "rightLowerArm": ((-0.12, 0, 0), (0.24, 0.06, 0.06), 2),
    "rightHand": ((-0.05, 0, 0), (0.1, 0.03, 0.08), 2),
    "leftUpperLeg": ((0, -0.2, 0), (0.1, 0.4, 0.1), 0), "leftLowerLeg": ((0, -0.21, 0), (0.08, 0.42, 0.08), 0),
    "leftFoot": ((0, -0.04, 0.05), (0.08, 0.08, 0.2), 0),
    "rightUpperLeg": ((0, -0.2, 0), (0.1, 0.4, 0.1), 0), "rightLowerLeg": ((0, -0.21, 0), (0.08, 0.42, 0.08), 0),
    "rightFoot": ((0, -0.04, 0.05), (0.08, 0.08, 0.2), 0),
}
NOSE = ((0, 0.1, 0.1), (0.03, 0.03, 0.05), 3)
COLORS = [(0.82, 0.8, 0.86), (0.9, 0.25, 0.25), (0.25, 0.45, 0.95), (1.0, 0.85, 0.1)]


def cube():
    faces = [((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
             ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
             ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
             ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
             ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
             ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)])]
    pos, nor, idx = [], [], []
    for n, quad in faces:
        base = len(pos) // 3
        for v in quad:
            pos += [c * 0.5 for c in v]
            nor += n
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nor, idx


def build(v0: bool) -> bytes:
    s = -1 if v0 else 1                                  # VRM 0.x mira a -Z: se giran X y Z
    flip = lambda p: (p[0] * s, p[1], p[2] * s)          # noqa: E731
    pos, nor, idx = cube()
    binary = struct.pack(f"<{len(pos)}f", *pos) + struct.pack(f"<{len(nor)}f", *nor) + struct.pack(f"<{len(idx)}H", *idx)
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos) * 4, "target": 34962},
             {"buffer": 0, "byteOffset": len(pos) * 4, "byteLength": len(nor) * 4, "target": 34962},
             {"buffer": 0, "byteOffset": (len(pos) + len(nor)) * 4, "byteLength": len(idx) * 2, "target": 34963}]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3", "min": [-0.5] * 3, "max": [0.5] * 3},
                 {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3"},
                 {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"}]
    materials = [{"name": f"m{i}", "pbrMetallicRoughness": {"baseColorFactor": [*c, 1], "metallicFactor": 0, "roughnessFactor": 0.9}}
                 for i, c in enumerate(COLORS)]
    meshes = [{"name": f"caja{i}", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": i}]}
              for i in range(len(COLORS))]

    nodes, index = [], {}
    for name, (parent, world) in SKELETON.items():
        origin = SKELETON[parent][1] if parent else (0, 0, 0)
        local = flip(tuple(world[i] - origin[i] for i in range(3)))
        index[name] = len(nodes)
        nodes.append({"name": name, "translation": list(local), "children": []})
    for name, (parent, _) in SKELETON.items():
        if parent:
            nodes[index[parent]]["children"].append(index[name])

    def add_box(bone, center, size, material):
        nodes[index[bone]]["children"].append(len(nodes))
        c = flip(center)
        nodes.append({"name": f"{bone}_caja", "translation": list(c), "scale": list(size), "mesh": material})

    for bone, (center, size, material) in BOXES.items():
        add_box(bone, center, size, material)
    add_box("head", *NOSE)
    for n in nodes:
        if not n.get("children"):
            n.pop("children", None)

    gltf = {"asset": {"version": "2.0", "generator": "companion-pc maniquí"}, "scene": 0,
            "scenes": [{"nodes": [index["hips"]]}], "nodes": nodes, "meshes": meshes, "materials": materials,
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    if v0:
        gltf["extensionsUsed"] = ["VRM"]
        gltf["extensions"] = {"VRM": {
            "exporterVersion": "companion-pc", "specVersion": "0.0",
            "meta": {"title": "Maniquí de prueba (VRM 0)", "author": "companion-pc", "allowedUserName": "Everyone",
                     "violentUssageName": "Disallow", "sexualUssageName": "Disallow", "commercialUssageName": "Disallow",
                     "licenseName": "CC0"},
            "humanoid": {"humanBones": [{"bone": b, "node": i, "useDefaultValues": True} for b, i in index.items()]},
            "firstPerson": {}, "blendShapeMaster": {"blendShapeGroups": []}, "secondaryAnimation": {},
            "materialProperties": []}}
    else:
        gltf["extensionsUsed"] = ["VRMC_vrm"]
        gltf["extensions"] = {"VRMC_vrm": {
            "specVersion": "1.0",
            "meta": {"name": "Maniquí de prueba (VRM 1)", "authors": ["companion-pc"],
                     "licenseUrl": "https://vrm.dev/licenses/1.0/", "avatarPermission": "everyone",
                     "commercialUsage": "personalNonProfit"},
            "humanoid": {"humanBones": {b: {"node": i} for b, i in index.items()}}}}

    js = json.dumps(gltf, ensure_ascii=False).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "maniqui.vrm"
    data = build("--v0" in sys.argv)
    with open(out, "wb") as f:
        f.write(data)
    print(f"{out}: {len(data)} bytes")
