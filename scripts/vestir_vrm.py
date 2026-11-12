"""Viste un modelo VRM «base» (sin ropa) generando prendas sobre la propia malla del cuerpo.

    .venv\\Scripts\\python.exe scripts\\vestir_vrm.py models\\base\\mika_base.vrm models\\mika.vrm

Cada prenda es una capa nueva de malla: copia los triángulos del cuerpo dentro de su zona, los separa unos
milímetros de la piel y hereda los mismos huesos y pesos, así que se deforma igual que el cuerpo al moverse.
El borde y el ribete de cada prenda salen de una textura de 1 píxel de alto indexada por la distancia al
borde, por eso quedan nítidos aunque la malla sea gruesa. La piel que queda tapada se quita para que no
asome al doblar las articulaciones. El archivo de entrada no se modifica.

Para ropa con vuelo (faldas, chaquetas, pelo de tela) hace falta modelarla en VRoid Studio o Blender.
"""
import argparse
import copy
import json
import struct
import zlib
from pathlib import Path

import numpy as np

DTYPE = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

# Rango de distancias al borde (metros) que cubre la textura de cada prenda.
D_MIN, D_MAX = -0.10, 0.22
TEX_W = 1024


def srgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


OUTFIT = {
    # prenda: colores sRGB, sombra (multiplica la textura), grosor sobre la piel y ancho del ribete
    "camiseta":   dict(main="#F4F1FA", trim="#8B6FE0", shade=(0.80, 0.78, 0.93), outline=(0.16, 0.13, 0.30),
                       offset=0.0065, trim_w=0.011, smooth=20, inflate=0.004),
    "short":      dict(main="#2D3157", trim="#8B6FE0", shade=(0.66, 0.66, 0.82), outline=(0.03, 0.03, 0.09),
                       offset=0.0040, trim_w=0.009, smooth=20, inflate=0.003),
    "calcetines": dict(main="#F4F1FA", trim="#8B6FE0", shade=(0.80, 0.78, 0.93), outline=(0.16, 0.13, 0.30),
                       offset=0.0030, trim_w=0.008, smooth=24, inflate=0.002),
}


# ---------------------------------------------------------------- GLB
def read_glb(path: Path) -> tuple[dict, bytearray]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise SystemExit("No es un archivo GLB/VRM")
    json_len, _ = struct.unpack_from("<II", data, 12)
    gltf = json.loads(data[20:20 + json_len].decode("utf-8"))
    bin_start = 20 + json_len
    bin_len, _ = struct.unpack_from("<II", data, bin_start)
    return gltf, bytearray(data[bin_start + 8:bin_start + 8 + bin_len])


def write_glb(path: Path, gltf: dict, binary: bytearray):
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    gltf["buffers"][0]["byteLength"] = len(binary)
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
                     + struct.pack("<II", len(binary), 0x004E4942) + binary)


def read_accessor(gltf: dict, binary: bytearray, index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    dtype, n = np.dtype(DTYPE[acc["componentType"]]), NCOMP[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or dtype.itemsize * n
    if stride == dtype.itemsize * n:
        arr = np.frombuffer(binary, dtype=dtype, count=acc["count"] * n, offset=start)
    else:
        raw = np.frombuffer(binary, dtype=np.uint8, count=stride * acc["count"], offset=start).reshape(acc["count"], stride)
        arr = raw[:, :dtype.itemsize * n].copy().view(dtype)
    return arr.reshape(acc["count"], n).copy()


def add_view(gltf: dict, binary: bytearray, data: bytes, target: int | None = None) -> int:
    binary.extend(b"\0" * (-len(binary) % 4))
    view = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
    if target:
        view["target"] = target
    binary.extend(data)
    gltf["bufferViews"].append(view)
    return len(gltf["bufferViews"]) - 1


def add_accessor(gltf: dict, binary: bytearray, arr: np.ndarray, kind: str, component: int, bounds=False, target=34962) -> int:
    arr = np.ascontiguousarray(arr, dtype=DTYPE[component])
    acc = {"bufferView": add_view(gltf, binary, arr.tobytes(), target), "componentType": component,
           "count": int(arr.shape[0]), "type": kind}
    if bounds:
        acc["min"], acc["max"] = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
    gltf["accessors"].append(acc)
    return len(gltf["accessors"]) - 1


def png_rgba(pixels: np.ndarray) -> bytes:
    h, w, _ = pixels.shape
    raw = b"".join(b"\0" + pixels[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- esqueleto
def human_bones(gltf: dict) -> tuple[dict[str, int], int]:
    """hueso humanoide → nodo, y hacia dónde mira el modelo (+1 = +Z en VRM 1.0, -1 = -Z en VRM 0.x)."""
    ext = gltf.get("extensions", {})
    if "VRMC_vrm" in ext:
        return {k: v["node"] for k, v in ext["VRMC_vrm"]["humanoid"]["humanBones"].items()}, 1
    if "VRM" in ext:
        return {b["bone"]: b["node"] for b in ext["VRM"]["humanoid"]["humanBones"]}, -1
    raise SystemExit("El archivo no es un VRM")


def descendants(gltf: dict, node: int) -> set[int]:
    out, stack = set(), [node]
    while stack:
        n = stack.pop()
        out.add(n)
        stack.extend(gltf["nodes"][n].get("children", []))
    return out


def dist_to_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


# ---------------------------------------------------------------- suavizado de la tela
def weld(P: np.ndarray) -> np.ndarray:
    """Agrupa los vértices duplicados en las costuras de la textura (misma posición)."""
    _, group = np.unique(np.round(P, 5), axis=0, return_inverse=True)
    return group.reshape(-1)


def smooth_shell(skin: np.ndarray, normal: np.ndarray, tris: np.ndarray, offset: float, weight: np.ndarray,
                 iterations: int) -> np.ndarray:
    """Coloca la tela a `offset` de la piel y la suaviza (laplaciano) para que no calque cada relieve del
    cuerpo: «tiende» entre los puntos altos. Tras cada pasada se la devuelve, como mínimo, a `offset` por
    fuera de la piel, así el suavizado solo puede rellenar huecos, nunca hundir la tela en el cuerpo."""
    group = weld(skin)
    n = group.max() + 1

    def per_group(values: np.ndarray) -> np.ndarray:
        acc = np.zeros((n,) + values.shape[1:])
        np.add.at(acc, group, values)
        return acc

    count = per_group(np.ones(len(skin)))
    g_skin = per_group(skin) / count[:, None]
    g_n = per_group(normal)
    g_n /= np.maximum(np.linalg.norm(g_n, axis=1, keepdims=True), 1e-12)
    g_w = np.full(n, 1.0)
    np.minimum.at(g_w, group, weight)
    g_pos = g_skin + g_n * offset
    gt = group[tris]
    edges = np.concatenate([gt[:, [0, 1]], gt[:, [1, 2]], gt[:, [2, 0]], gt[:, [1, 0]], gt[:, [2, 1]], gt[:, [0, 2]]])
    edges = np.unique(edges[edges[:, 0] != edges[:, 1]], axis=0)
    deg = np.bincount(edges[:, 0], minlength=n).astype(float)
    deg[deg == 0] = 1
    for _ in range(iterations):
        acc = np.zeros((n, 3))
        np.add.at(acc, edges[:, 0], g_pos[edges[:, 1]])
        g_pos += (acc / deg[:, None] - g_pos) * (0.5 * g_w[:, None])
        lift = offset - ((g_pos - g_skin) * g_n).sum(axis=1)
        g_pos += g_n * np.maximum(lift, 0)[:, None]
    return g_pos[group]


def vertex_normals(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    group = weld(pos)
    face = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    acc = np.zeros((group.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, group[tris[:, k]], face)
    acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
    return acc[group]


# ---------------------------------------------------------------- prendas
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path)
    ap.add_argument("salida", type=Path)
    ap.add_argument("--manga", type=float, default=0.5, help="largo de la manga: 0 = sin manga, 0.5 = media, 1 = hasta el codo, 2 = hasta la muñeca")
    ap.add_argument("--pierna", type=float, default=0.42, help="largo del short: fracción del muslo (1 = hasta la rodilla)")
    ap.add_argument("--sin", nargs="*", default=[], choices=list(OUTFIT), help="prendas que no se generan")
    args = ap.parse_args()

    gltf, binary = read_glb(args.entrada)
    if any(m.get("name", "").startswith("Ropa_") for m in gltf["materials"]):
        raise SystemExit("Ese modelo ya fue vestido por este script: usa el archivo base como entrada.")
    bones, front = human_bones(gltf)

    mesh_index = next(i for i, m in enumerate(gltf["meshes"]) if m.get("name") == "Body")
    mesh = gltf["meshes"][mesh_index]
    node = next(n for n in gltf["nodes"] if n.get("mesh") == mesh_index)
    skin = gltf["skins"][node["skin"]]
    skin_prims = [p for p in mesh["primitives"] if "SKIN" in gltf["materials"][p["material"]]["name"].upper()]
    if not skin_prims:
        raise SystemExit("No encontré la piel del cuerpo (material *_SKIN en la malla Body)")
    attrs = skin_prims[0]["attributes"]
    assert all(p["attributes"]["POSITION"] == attrs["POSITION"] for p in skin_prims), "primitivas con vértices distintos"
    body_material = gltf["materials"][skin_prims[0]["material"]]

    P = read_accessor(gltf, binary, attrs["POSITION"]).astype(np.float64)
    N = read_accessor(gltf, binary, attrs["NORMAL"]).astype(np.float64)
    J = read_accessor(gltf, binary, attrs["JOINTS_0"])
    W = read_accessor(gltf, binary, attrs["WEIGHTS_0"]).astype(np.float64)
    prim_tris = [read_accessor(gltf, binary, p["indices"]).reshape(-1, 3).astype(np.int64) for p in skin_prims]
    tris = np.concatenate(prim_tris)

    # Posición de cada hueso en la pose de la malla (inversa de su matriz de enlace).
    ibm = read_accessor(gltf, binary, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    joint_of = {n: j for j, n in enumerate(skin["joints"])}
    L = {name: np.linalg.inv(ibm[joint_of[n]])[:3, 3] for name, n in bones.items() if n in joint_of}

    def weight_on(roots: list[str]) -> np.ndarray:
        joints = {joint_of[n] for r in roots if r in bones for n in descendants(gltf, bones[r]) if n in joint_of}
        return (W * np.isin(J, list(joints))).sum(axis=1)

    w_arm = weight_on(["leftUpperArm", "rightUpperArm"])
    w_leg = weight_on(["leftUpperLeg", "rightUpperLeg"])
    x, y = P[:, 0], P[:, 1]
    side = np.where(x * front >= 0, "left", "right")

    print(f"cuerpo: {len(P)} vértices, {len(tris)} triángulos · mira a {'+Z' if front > 0 else '-Z'}")
    for k in ("head", "neck", "upperChest", "hips", "leftUpperArm", "leftLowerArm", "leftHand", "leftUpperLeg", "leftLowerLeg", "leftFoot"):
        print(f"   {k:14} {np.round(L[k], 3)}")

    # --- camiseta: cuello redondo, mangas a lo largo de cada brazo, bajo a la altura de la cadera
    def along_arm(s: str) -> np.ndarray:
        ua, la, hand = L[f"{s}UpperArm"], L[f"{s}LowerArm"], L[f"{s}Hand"]
        upper, lower = np.linalg.norm(la - ua), np.linalg.norm(hand - la)
        reach = (P - ua) @ ((hand - ua) / np.linalg.norm(hand - ua))
        length = args.manga * upper if args.manga <= 1 else upper + (args.manga - 1) * lower * 0.96
        return length - reach

    sleeve = np.where(side == "left", along_arm("left"), along_arm("right"))
    shoulder_w = abs(L["leftUpperArm"][0])
    collar_from = L["neck"] + np.array([0, -0.012, 0.012 * front])
    collar = dist_to_segment(P, collar_from, L["head"] + np.array([0, 0.3, 0])) - 0.60 * shoulder_w
    hem = y - (L["hips"][1] - 0.035)
    d_shirt = np.minimum.reduce([sleeve, collar, hem])
    d_shirt[w_leg > 0.5] = np.minimum(d_shirt[w_leg > 0.5], hem[w_leg > 0.5])

    # --- short: de la cintura a medio muslo
    thigh = L["leftUpperLeg"][1] - L["leftLowerLeg"][1]
    d_short = np.minimum((L["hips"][1] + 0.055) - y, y - (L["leftUpperLeg"][1] - args.pierna * thigh))
    d_short[w_arm > 0.5] = -1.0

    # --- calcetines cortos
    d_sock = (L["leftFoot"][1] + 0.075) - y
    d_sock[w_leg < 0.5] = -1.0

    fields = {"camiseta": d_shirt, "short": d_short, "calcetines": d_sock}
    # Dónde se permite suavizar cada prenda: las mangas no (perderían forma) y el short solo por debajo
    # del bajo de la camiseta, para que nunca sobresalga por encima de ella.
    zone = {"camiseta": np.clip(1 - 2.5 * w_arm, 0, 1),
            "short": np.clip(((L["hips"][1] - 0.035) - y) / 0.03, 0, 1),
            "calcetines": np.ones(len(P))}

    gltf.setdefault("samplers", []).append({"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071})
    sampler = len(gltf["samplers"]) - 1
    hidden = np.zeros(len(P), dtype=bool)

    for name, cfg in OUTFIT.items():
        if name in args.sin:
            continue
        d = fields[name]
        keep = (d[tris] > 0).any(axis=1)
        if not keep.any():
            print(f"{name}: no cubre ningún triángulo, se omite")
            continue
        t = tris[keep]
        used = np.unique(t)
        remap = np.full(len(P), -1, dtype=np.int64)
        remap[used] = np.arange(len(used))
        t = remap[t]
        dd = d[used]

        w_smooth = np.clip((dd - 0.012) / 0.05, 0, 1) * zone[name][used]   # cerca del borde la tela no se mueve
        pos = smooth_shell(P[used], N[used], t, cfg["offset"], w_smooth, cfg["smooth"])
        normals = vertex_normals(pos, t) if cfg["smooth"] else N[used]
        pos = pos + normals * (cfg["inflate"] * w_smooth)[:, None]

        u = (np.clip(dd, D_MIN, D_MAX) - D_MIN) / (D_MAX - D_MIN)
        uv = np.stack([u, np.full_like(u, 0.5)], axis=1)

        # Textura: transparente fuera de la prenda, ribete junto al borde, color principal dentro.
        texel_d = (np.arange(TEX_W) + 0.5) / TEX_W * (D_MAX - D_MIN) + D_MIN
        row = np.zeros((TEX_W, 4), dtype=np.uint8)
        row[:, :3] = np.where((texel_d < cfg["trim_w"])[:, None], srgb(cfg["trim"]), srgb(cfg["main"]))
        row[:, 3] = np.where(texel_d >= 0, 255, 0)
        png = png_rgba(np.repeat(row[None], 4, axis=0))
        gltf["images"].append({"name": f"Ropa_{name}", "bufferView": add_view(gltf, binary, png), "mimeType": "image/png"})
        gltf["textures"].append({"sampler": sampler, "source": len(gltf["images"]) - 1, "name": f"Ropa_{name}"})
        tex = len(gltf["textures"]) - 1

        mat = copy.deepcopy(body_material)
        mat["name"] = f"Ropa_{name}"
        mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex, "texCoord": 0}
        mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
        for key in ("normalTexture", "emissiveTexture"):
            mat.pop(key, None)
        mat.update(alphaMode="MASK", alphaCutoff=0.5, doubleSided=True)
        mtoon = mat.get("extensions", {}).get("VRMC_materials_mtoon")
        if mtoon is not None:
            mtoon.update(shadeColorFactor=list(cfg["shade"]), shadeMultiplyTexture={"index": tex},
                         outlineColorFactor=list(cfg["outline"]), matcapFactor=[0, 0, 0])
            for key in ("matcapTexture", "rimMultiplyTexture", "shadingShiftTexture", "outlineWidthMultiplyTexture",
                        "uvAnimationMaskTexture"):
                mtoon.pop(key, None)
        vrm0_props = gltf.get("extensions", {}).get("VRM", {}).get("materialProperties")
        gltf["materials"].append(mat)
        if vrm0_props is not None:                       # VRM 0.x guarda los ajustes MToon en una lista paralela
            prop = copy.deepcopy(vrm0_props[skin_prims[0]["material"]])
            prop["name"] = mat["name"]
            vrm0_props.append(prop)

        mesh["primitives"].append({
            "attributes": {
                "POSITION": add_accessor(gltf, binary, pos, "VEC3", 5126, bounds=True),
                "NORMAL": add_accessor(gltf, binary, normals, "VEC3", 5126),
                "TEXCOORD_0": add_accessor(gltf, binary, uv, "VEC2", 5126),
                "JOINTS_0": add_accessor(gltf, binary, J[used], "VEC4", 5123),
                "WEIGHTS_0": add_accessor(gltf, binary, W[used], "VEC4", 5126),
            },
            "indices": add_accessor(gltf, binary, t.reshape(-1, 1), "SCALAR", 5125, target=34963),
            "material": len(gltf["materials"]) - 1, "mode": 4,
        })
        hidden |= d > 0.018
        print(f"{name}: {len(used)} vértices, {len(t)} triángulos")

    # La piel totalmente tapada se retira (así no asoma al doblar codos, hombros o cintura).
    removed = 0
    for prim, pt in zip(skin_prims, prim_tris):
        visible = ~hidden[pt].all(axis=1)
        removed += int((~visible).sum())
        prim["indices"] = add_accessor(gltf, binary, pt[visible].reshape(-1, 1), "SCALAR", 5125, target=34963)
    print(f"piel oculta retirada: {removed} triángulos")

    write_glb(args.salida, gltf, binary)
    print(f"{args.salida}: {args.salida.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
