"""Lectura y validación de modelos VRM (0.x y 1.0). Tomado de waifuv3 (mac-backend/app/vrm.py).

Un .vrm es un glTF binario (GLB): cabecera de 12 bytes + chunk JSON + chunk binario.
Aquí solo se lee el JSON para validar el formato y extraer el nombre y la licencia.
"""
import json
import struct

GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A


class VRMError(ValueError):
    pass


def read_gltf_json(data: bytes) -> dict:
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise VRMError("No es un archivo GLB/VRM válido")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise VRMError(f"glTF versión {version} no soportada")
    if length > len(data):
        raise VRMError("Archivo truncado")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != CHUNK_JSON:
        raise VRMError("El primer chunk no es JSON")
    return json.loads(data[20:20 + chunk_len].decode("utf-8"))


def read_gltf_json_file(path) -> dict:
    """Como read_gltf_json, pero leyendo del disco solo la cabecera y el JSON (no los ~15 MB de mallas)."""
    with open(path, "rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != GLB_MAGIC:
            raise VRMError("No es un archivo GLB/VRM válido")
        chunk_len, chunk_type = struct.unpack_from("<II", head, 12)
        if chunk_type != CHUNK_JSON:
            raise VRMError("El primer chunk no es JSON")
        return json.loads(f.read(chunk_len).decode("utf-8"))


def extract_meta(gltf: dict) -> dict:
    ext = gltf.get("extensions", {})
    if "VRMC_vrm" in ext:
        m = ext["VRMC_vrm"].get("meta", {})
        return {"spec": "1.0", "name": m.get("name"), "authors": m.get("authors", []),
                "license_url": m.get("licenseUrl"),
                "avatar_permission": m.get("avatarPermission", "onlyAuthor"),
                "commercial_usage": m.get("commercialUsage", "personalNonProfit"),
                "allow_sexual": bool(m.get("allowExcessivelySexualUsage", False)),
                "expressions": sorted((ext["VRMC_vrm"].get("expressions", {}).get("preset") or {}).keys())}
    if "VRM" in ext:
        m = ext["VRM"].get("meta", {})
        return {"spec": "0.x", "name": m.get("title"), "authors": [m["author"]] if m.get("author") else [],
                "license_url": m.get("otherPermissionUrl") or m.get("licenseName"),
                "avatar_permission": m.get("allowedUserName", "OnlyAuthor"),
                "commercial_usage": m.get("commercialUssageName", "Disallow"),
                "allow_sexual": m.get("sexualUssageName") == "Allow",
                "expressions": [g.get("presetName") for g in
                                ext["VRM"].get("blendShapeMaster", {}).get("blendShapeGroups", [])]}
    raise VRMError("El archivo es glTF pero no tiene extensión VRM (VRMC_vrm ni VRM)")


def license_warnings(meta: dict) -> list[str]:
    w = []
    if not meta["allow_sexual"]:
        w.append("La licencia del autor no permite usos sexuales; no lo uses en modo +18 fuera de tus pruebas privadas.")
    if meta["avatar_permission"] in ("onlyAuthor", "OnlyAuthor"):
        w.append("La licencia solo permite que el autor use el avatar.")
    if meta["commercial_usage"] in ("personalNonProfit", "Disallow"):
        w.append("La licencia no permite uso comercial.")
    return w
