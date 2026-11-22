use crate::config::AppConfig;
use regex::Regex;
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

const GLB_MAGIC: &[u8; 4] = b"glTF";
const CHUNK_JSON: u32 = 0x4E4F534A;
pub const MAX_MB: usize = 200;

struct BuiltinModel {
    id: &'static str,
    name: &'static str,
    file: Option<&'static str>,
    note: &'static str,
}

const BUILTIN: &[BuiltinModel] = &[
    BuiltinModel { id: "avatar1", name: "Avatar 1", file: Some("avatar1.vrm"), note: "Personaje incluido" },
    BuiltinModel { id: "avatar2", name: "Avatar 2", file: Some("avatar2.vrm"), note: "Personaje incluido" },
    BuiltinModel { id: "avatar3", name: "Avatar 3 (Orbe ligero)", file: None, note: "Una esfera ligera que cambia de color con lo que siente" },
];

fn legacy_map(id: &str) -> &str {
    match id {
        "default" | "chica" => "avatar1",
        "chico" => "avatar2",
        "esfera" => "avatar3",
        other => other,
    }
}

fn id_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[a-z0-9_-]{1,60}$").unwrap())
}

fn stem_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[^a-z0-9_-]+").unwrap())
}

fn read_gltf_json_bytes(data: &[u8]) -> Result<Value, String> {
    if data.len() < 20 || &data[0..4] != GLB_MAGIC {
        return Err("No es un archivo GLB/VRM válido".into());
    }
    let version = u32::from_le_bytes(data[4..8].try_into().unwrap());
    let length = u32::from_le_bytes(data[8..12].try_into().unwrap()) as usize;
    if version != 2 {
        return Err(format!("glTF versión {version} no soportada"));
    }
    if length > data.len() {
        return Err("Archivo truncado".into());
    }
    let chunk_len = u32::from_le_bytes(data[12..16].try_into().unwrap()) as usize;
    let chunk_type = u32::from_le_bytes(data[16..20].try_into().unwrap());
    if chunk_type != CHUNK_JSON || 20 + chunk_len > data.len() {
        return Err("El primer chunk no es JSON".into());
    }
    serde_json::from_slice(&data[20..20 + chunk_len]).map_err(|e| format!("JSON inválido: {e}"))
}

fn read_gltf_json_file(path: &Path) -> Result<Value, String> {
    let mut f = File::open(path).map_err(|e| e.to_string())?;
    let mut head = [0u8; 20];
    f.read_exact(&mut head).map_err(|e| e.to_string())?;
    if &head[0..4] != GLB_MAGIC {
        return Err("No es un archivo GLB/VRM válido".into());
    }
    let chunk_len = u32::from_le_bytes(head[12..16].try_into().unwrap()) as usize;
    let chunk_type = u32::from_le_bytes(head[16..20].try_into().unwrap());
    if chunk_type != CHUNK_JSON || chunk_len > 16 * 1024 * 1024 {
        return Err("El primer chunk no es JSON".into());
    }
    let mut buf = vec![0u8; chunk_len];
    f.read_exact(&mut buf).map_err(|e| e.to_string())?;
    serde_json::from_slice(&buf).map_err(|e| e.to_string())
}

fn extract_meta(gltf: &Value) -> Result<Value, String> {
    let ext = gltf.get("extensions").and_then(|v| v.as_object());
    if let Some(vrm1) = ext.and_then(|e| e.get("VRMC_vrm")) {
        let m = vrm1.get("meta").and_then(|v| v.as_object());
        return Ok(json!({
            "spec": "1.0",
            "name": m.and_then(|o| o.get("name")).and_then(|v| v.as_str()),
            "authors": m.and_then(|o| o.get("authors")).cloned().unwrap_or_else(|| json!([])),
            "license_url": m.and_then(|o| o.get("licenseUrl")).and_then(|v| v.as_str()),
            "avatar_permission": m.and_then(|o| o.get("avatarPermission")).and_then(|v| v.as_str()).unwrap_or("onlyAuthor"),
            "commercial_usage": m.and_then(|o| o.get("commercialUsage")).and_then(|v| v.as_str()).unwrap_or("personalNonProfit"),
            "allow_sexual": m.and_then(|o| o.get("allowExcessivelySexualUsage")).and_then(|v| v.as_bool()).unwrap_or(false),
        }));
    }
    if let Some(vrm0) = ext.and_then(|e| e.get("VRM")) {
        let m = vrm0.get("meta").and_then(|v| v.as_object());
        let author = m.and_then(|o| o.get("author")).and_then(|v| v.as_str());
        return Ok(json!({
            "spec": "0.x",
            "name": m.and_then(|o| o.get("title")).and_then(|v| v.as_str()),
            "authors": author.map(|a| json!([a])).unwrap_or_else(|| json!([])),
            "license_url": m.and_then(|o| o.get("otherPermissionUrl").or_else(|| o.get("licenseName"))).and_then(|v| v.as_str()),
            "avatar_permission": m.and_then(|o| o.get("allowedUserName")).and_then(|v| v.as_str()).unwrap_or("OnlyAuthor"),
            "commercial_usage": m.and_then(|o| o.get("commercialUssageName")).and_then(|v| v.as_str()).unwrap_or("Disallow"),
            "allow_sexual": m.and_then(|o| o.get("sexualUssageName")).and_then(|v| v.as_str()) == Some("Allow"),
        }));
    }
    Err("El archivo es glTF pero no tiene extensión VRM (VRMC_vrm ni VRM)".into())
}

fn builtin_available(cfg: &AppConfig, b: &BuiltinModel) -> bool {
    match b.file {
        None => true,
        Some(f) => cfg.models_dir.join(f).is_file(),
    }
}

fn custom_dir(cfg: &AppConfig) -> PathBuf {
    cfg.models_dir.join("custom")
}

pub fn active_id(cfg: &AppConfig) -> String {
    if cfg.is_lite() {
        return "avatar3".to_string();
    }
    let s = cfg.load_settings();
    let raw = s.get("model").and_then(|v| v.as_str()).unwrap_or("avatar1");
    let wanted = legacy_map(raw);
    if let Some(b) = BUILTIN.iter().find(|b| b.id == wanted) {
        if builtin_available(cfg, b) {
            return b.id.to_string();
        }
    } else if id_re().is_match(wanted) && custom_dir(cfg).join(format!("{wanted}.vrm")).is_file() {
        return wanted.to_string();
    }
    BUILTIN
        .iter()
        .find(|b| builtin_available(cfg, b))
        .map(|b| b.id.to_string())
        .unwrap_or_else(|| "avatar3".to_string())
}

pub fn active_kind(cfg: &AppConfig) -> &'static str {
    let id = active_id(cfg);
    if BUILTIN.iter().any(|b| b.id == id && b.file.is_none()) {
        "orb"
    } else {
        "vrm"
    }
}

pub fn active_path(cfg: &AppConfig) -> Option<PathBuf> {
    let id = active_id(cfg);
    if let Some(b) = BUILTIN.iter().find(|b| b.id == id) {
        return b.file.map(|f| cfg.models_dir.join(f));
    }
    let p = custom_dir(cfg).join(format!("{id}.vrm"));
    if p.is_file() { Some(p) } else { None }
}

pub fn custom_list(cfg: &AppConfig) -> Vec<Value> {
    let dir = custom_dir(cfg);
    let Ok(entries) = fs::read_dir(&dir) else {
        return vec![];
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("vrm"))
        .collect();
    paths.sort();

    let mut out = Vec::new();
    for path in paths {
        let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
            continue;
        };
        if BUILTIN.iter().any(|b| b.id == stem) {
            continue;
        }
        let Ok(gltf) = read_gltf_json_file(&path) else {
            continue;
        };
        let Ok(meta) = extract_meta(&gltf) else {
            continue;
        };
        let size_mb = fs::metadata(&path)
            .map(|m| (m.len() as f64 / 1e6 * 10.0).round() / 10.0)
            .unwrap_or(0.0);
        out.push(json!({
            "id": stem,
            "name": meta.get("name").and_then(|v| v.as_str()).unwrap_or(stem),
            "spec": meta.get("spec").and_then(|v| v.as_str()).unwrap_or("1.0"),
            "size_mb": size_mb,
        }));
    }
    out
}

pub fn listing(cfg: &AppConfig) -> Value {
    let builtin: Vec<Value> = BUILTIN
        .iter()
        .map(|b| {
            json!({
                "id": b.id,
                "name": b.name,
                "note": b.note,
                "available": builtin_available(cfg, b),
            })
        })
        .collect();
    json!({
        "active": active_id(cfg),
        "builtin": builtin,
        "custom": custom_list(cfg),
    })
}

pub fn select(cfg: &AppConfig, model_id: &str) -> Result<(), String> {
    let id = legacy_map(model_id);
    if let Some(b) = BUILTIN.iter().find(|b| b.id == id) {
        if !builtin_available(cfg, b) {
            return Err("Ese personaje no está instalado".into());
        }
    } else if !id_re().is_match(id) || !custom_dir(cfg).join(format!("{id}.vrm")).is_file() {
        return Err("Ese modelo no existe".into());
    }
    cfg.update_settings(|obj| {
        obj.insert("model".into(), json!(id));
    });
    Ok(())
}

pub fn add_custom(cfg: &AppConfig, filename: &str, data: &[u8]) -> Result<Value, String> {
    let gltf = read_gltf_json_bytes(data)?;
    let meta = extract_meta(&gltf)?;
    let raw_stem = Path::new(filename)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("modelo")
        .to_lowercase();
    let mut stem = stem_re()
        .replace_all(&raw_stem, "-")
        .trim_matches('-')
        .chars()
        .take(48)
        .collect::<String>();
    if stem.is_empty() {
        stem = "modelo".into();
    }
    if BUILTIN.iter().any(|b| b.id == stem) || matches!(stem.as_str(), "default" | "chica" | "chico" | "esfera") {
        stem = format!("{stem}-propio");
    }
    let dir = custom_dir(cfg);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let mut model_id = stem.clone();
    let mut n = 2;
    while dir.join(format!("{model_id}.vrm")).exists() {
        model_id = format!("{stem}-{n}");
        n += 1;
    }
    fs::write(dir.join(format!("{model_id}.vrm")), data).map_err(|e| e.to_string())?;
    cfg.update_settings(|obj| {
        obj.insert("model".into(), json!(model_id));
    });
    Ok(json!({
        "id": model_id,
        "meta": meta,
        "license_warnings": [],
    }))
}

pub fn remove_custom(cfg: &AppConfig, model_id: &str) -> Result<(), String> {
    if BUILTIN.iter().any(|b| b.id == model_id) || !id_re().is_match(model_id) {
        return Err("Solo se pueden quitar los modelos propios".into());
    }
    let path = custom_dir(cfg).join(format!("{model_id}.vrm"));
    if !path.is_file() {
        return Err("Solo se pueden quitar los modelos propios".into());
    }
    fs::remove_file(&path).map_err(|e| e.to_string())?;
    if active_id(cfg) == model_id {
        cfg.update_settings(|obj| {
            obj.insert("model".into(), json!("avatar1"));
        });
    }
    Ok(())
}
