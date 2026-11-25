use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::RwLock;

#[cfg(windows)]
pub fn seal_secret(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.starts_with("dpapi:") {
        return trimmed.to_string();
    }
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let mut bytes = trimmed.as_bytes().to_vec();
    let in_blob = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_mut_ptr(),
    };
    let mut out_blob = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: null_mut(),
    };
    unsafe {
        if CryptProtectData(
            &in_blob,
            null(),
            null(),
            null_mut(),
            null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out_blob,
        ) != 0
            && !out_blob.pbData.is_null()
        {
            let slice = std::slice::from_raw_parts(out_blob.pbData, out_blob.cbData as usize);
            let encoded = format!("dpapi:{}", B64.encode(slice));
            LocalFree(out_blob.pbData as _);
            return encoded;
        }
    }
    trimmed.to_string()
}

#[cfg(not(windows))]
pub fn seal_secret(raw: &str) -> String {
    raw.trim().to_string()
}

#[cfg(windows)]
pub fn unseal_secret(stored: &str) -> String {
    let trimmed = stored.trim();
    let Some(b64) = trimmed.strip_prefix("dpapi:") else {
        if trimmed.starts_with("keychain:") {
            return String::new();
        }
        return trimmed.to_string();
    };
    let Ok(mut raw) = B64.decode(b64) else {
        return String::new();
    };
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let in_blob = CRYPT_INTEGER_BLOB {
        cbData: raw.len() as u32,
        pbData: raw.as_mut_ptr(),
    };
    let mut out_blob = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: null_mut(),
    };
    unsafe {
        if CryptUnprotectData(
            &in_blob,
            null_mut(),
            null(),
            null_mut(),
            null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out_blob,
        ) != 0
            && !out_blob.pbData.is_null()
        {
            let slice = std::slice::from_raw_parts(out_blob.pbData, out_blob.cbData as usize);
            let plain = String::from_utf8_lossy(slice).to_string();
            LocalFree(out_blob.pbData as _);
            return plain;
        }
    }
    String::new()
}

#[cfg(not(windows))]
pub fn unseal_secret(stored: &str) -> String {
    let trimmed = stored.trim();
    if trimmed.starts_with("dpapi:") || trimmed.starts_with("keychain:") {
        return String::new();
    }
    trimmed.to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiveProviderMeta {
    pub id: String,
    pub name: String,
    pub free: String,
    pub keys: String,
    pub url: String,
    pub flavor: String, // "gemini" | "ga" | "beta"
    pub rate: u32,
    pub out_format: String,
    pub models: Vec<String>,
    pub voices: Vec<String>,
    pub voice_f: String,
    pub voice_m: String,
    pub note: String,
}

pub fn live_providers() -> Vec<LiveProviderMeta> {
    vec![
        LiveProviderMeta {
            id: "gemini".into(),
            name: "Google Gemini Live".into(),
            free: "gratis con límite diario".into(),
            keys: "https://aistudio.google.com/apikey".into(),
            url: "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent".into(),
            flavor: "gemini".into(),
            rate: 16000,
            out_format: "pcm16".into(),
            models: vec!["gemini-3.1-flash-live-preview".into(), "gemini-2.5-flash-native-audio-preview-09-2025".into()],
            voices: vec!["Aoede".into(), "Kore".into(), "Leda".into(), "Zephyr".into(), "Puck".into(), "Charon".into(), "Fenrir".into(), "Orus".into()],
            voice_f: "Aoede".into(),
            voice_m: "Puck".into(),
            note: "Tiene capa gratuita (con límite diario). Usa la clave de Gemini si no pones otra. Probado.".into(),
        },
        LiveProviderMeta {
            id: "openai".into(),
            name: "OpenAI Realtime".into(),
            free: "".into(),
            keys: "https://platform.openai.com/api-keys".into(),
            url: "wss://api.openai.com/v1/realtime".into(),
            flavor: "ga".into(),
            rate: 24000,
            out_format: "pcm16".into(),
            models: vec!["gpt-realtime".into(), "gpt-realtime-mini".into()],
            voices: vec!["marin".into(), "cedar".into(), "coral".into(), "shimmer".into(), "sage".into(), "alloy".into(), "ash".into(), "ballad".into(), "echo".into(), "verse".into()],
            voice_f: "marin".into(),
            voice_m: "cedar".into(),
            note: "De pago (por minuto de audio).".into(),
        },
        LiveProviderMeta {
            id: "xai".into(),
            name: "xAI Grok Voice".into(),
            free: "".into(),
            keys: "https://console.x.ai".into(),
            url: "wss://api.x.ai/v1/realtime".into(),
            flavor: "beta".into(),
            rate: 24000,
            out_format: "pcm16".into(),
            models: vec!["grok-voice-latest".into()],
            voices: vec!["Ara".into(), "Eve".into(), "Rex".into(), "Sal".into(), "Leo".into()],
            voice_f: "Ara".into(),
            voice_m: "Rex".into(),
            note: "De pago (~0,08 USD/min).".into(),
        },
        LiveProviderMeta {
            id: "qwen".into(),
            name: "Qwen Omni Realtime (Alibaba)".into(),
            free: "cuota gratis al empezar".into(),
            keys: "https://modelstudio.console.alibabacloud.com".into(),
            url: "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime".into(),
            flavor: "beta".into(),
            rate: 16000,
            out_format: "pcm24".into(),
            models: vec!["qwen3-omni-flash-realtime".into()],
            voices: vec!["Cherry".into(), "Serena".into(), "Chelsie".into(), "Ethan".into()],
            voice_f: "Cherry".into(),
            voice_m: "Ethan".into(),
            note: "Cuota gratuita al abrir la cuenta y luego muy barato. Clave región internacional (Singapur).".into(),
        },
        LiveProviderMeta {
            id: "custom".into(),
            name: "Otro (compatible con OpenAI Realtime)".into(),
            free: "".into(),
            keys: "".into(),
            url: "".into(),
            flavor: "ga".into(),
            rate: 24000,
            out_format: "pcm16".into(),
            models: vec![],
            voices: vec![],
            voice_f: "".into(),
            voice_m: "".into(),
            note: "Escribe la dirección wss:// de su API (por ejemplo Azure OpenAI).".into(),
        },
    ]
}

pub fn provider_meta(id: &str) -> LiveProviderMeta {
    let all = live_providers();
    all.into_iter()
        .find(|p| p.id == id)
        .unwrap_or_else(|| live_providers().remove(0))
}

#[derive(Debug, Clone)]
pub struct LiveConfig {
    pub provider: String,
    pub key: String,
    pub model: String,
    pub voice: String,
    pub url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserProfile {
    pub name: String,
    pub birth_year: Option<i32>,
    pub gender: String,
}

pub struct AppConfig {
    pub root: PathBuf,
    pub data_dir: PathBuf,
    pub web_dir: PathBuf,
    pub models_dir: PathBuf,
    pub personas_dir: PathBuf,
    pub port: u16,
    pub started: f64,
    pub barge_in: bool,
    pub lite_mode: bool,
    pub env_map: HashMap<String, String>,
    pub persona_base: Value,
    settings_lock: RwLock<Value>,
}

impl AppConfig {
    pub fn load(root: PathBuf, port: u16, lite_mode: bool) -> Self {
        let data_dir = root.join("data");
        let web_dir = root.join("web");
        let models_dir = root.join("models");
        let personas_dir = root.join("personas");
        let _ = fs::create_dir_all(&data_dir);

        let env_map = parse_env_file(&root.join(".env"));
        let settings_path = data_dir.join("settings.json");
        let settings_val = fs::read_to_string(&settings_path)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .filter(|v| v.is_object())
            .unwrap_or_else(|| json!({}));

        let persona_file = env_map
            .get("PERSONA_FILE")
            .cloned()
            .unwrap_or_else(|| "personas/mika.json".to_string());
        let p_path = if Path::new(&persona_file).is_absolute() {
            PathBuf::from(&persona_file)
        } else {
            root.join(&persona_file)
        };
        let persona_base = fs::read_to_string(&p_path)
            .ok()
            .or_else(|| crate::assets::embedded_persona_file("mika.json"))
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .unwrap_or_else(|| {
                json!({
                    "name": "Mika",
                    "age": 22,
                    "speaks": "f",
                    "role": "asistente personal y compañera cercana",
                    "backstory": "Una compañera de escritorio cercana y expresiva.",
                    "traits": {},
                    "speech_style": {"formality": "casual", "notes": ""},
                    "voice": {"id": "mika"}
                })
            });

        let barge_in = env_map
            .get("BARGE_IN")
            .map(|v| v != "0" && v.to_lowercase() != "false")
            .unwrap_or(true);

        let started = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);

        Self {
            root,
            data_dir,
            web_dir,
            models_dir,
            personas_dir,
            port,
            started,
            barge_in,
            lite_mode,
            env_map,
            persona_base,
            settings_lock: RwLock::new(settings_val),
        }
    }

    pub fn settings_path(&self) -> PathBuf {
        self.data_dir.join("settings.json")
    }

    pub fn load_settings(&self) -> Value {
        self.settings_lock
            .read()
            .map(|g| g.clone())
            .unwrap_or_else(|_| json!({}))
    }

    pub fn update_settings<F>(&self, f: F) -> Value
    where
        F: FnOnce(&mut Map<String, Value>),
    {
        let mut guard = self.settings_lock.write().unwrap();
        if !guard.is_object() {
            *guard = json!({});
        }
        if let Some(obj) = guard.as_object_mut() {
            f(obj);
        }
        let cloned = guard.clone();
        let path = self.settings_path();
        let tmp = path.with_extension("tmp");
        if let Ok(text) = serde_json::to_string_pretty(&cloned) {
            if fs::write(&tmp, text).is_ok() {
                let _ = fs::rename(&tmp, &path);
            }
        }
        cloned
    }

    pub fn env_or(&self, key: &str, default: &str) -> String {
        std::env::var(key)
            .ok()
            .filter(|v| !v.is_empty())
            .or_else(|| self.env_map.get(key).cloned().filter(|v| !v.is_empty()))
            .unwrap_or_else(|| default.to_string())
    }

    pub fn character_name(&self) -> String {
        self.persona_base
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("Mika")
            .to_string()
    }

    pub fn user_profile(&self) -> UserProfile {
        let s = self.load_settings();
        let p = s.get("profile").and_then(|v| v.as_object());
        let name = p
            .and_then(|o| o.get("name"))
            .and_then(|v| v.as_str())
            .filter(|v| !v.trim().is_empty())
            .map(|v| v.to_string())
            .unwrap_or_else(|| self.env_or("USER_NAME", "tú"));
        let birth_year = p
            .and_then(|o| o.get("birth_year"))
            .and_then(|v| v.as_i64())
            .map(|v| v as i32);
        let gender = p
            .and_then(|o| o.get("gender"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        UserProfile {
            name,
            birth_year,
            gender,
        }
    }

    pub fn live_config(&self) -> LiveConfig {
        let s = self.load_settings();
        let lv = s.get("live").and_then(|v| v.as_object());
        let prov = lv
            .and_then(|o| o.get("provider"))
            .and_then(|v| v.as_str())
            .filter(|p| live_providers().iter().any(|m| m.id == *p))
            .unwrap_or("gemini")
            .to_string();
        let meta = provider_meta(&prov);

        let mut key = lv
            .and_then(|o| o.get("key"))
            .and_then(|v| v.as_str())
            .map(unseal_secret)
            .unwrap_or_default()
            .trim()
            .to_string();

        if key.is_empty() && prov == "gemini" {
            // Fallback to cloud.key if cloud.preset == gemini, or GEMINI_API_KEY in .env
            let cloud_key = s
                .get("cloud")
                .and_then(|c| c.as_object())
                .filter(|c| c.get("preset").and_then(|v| v.as_str()).unwrap_or("gemini") == "gemini")
                .and_then(|c| c.get("key"))
                .and_then(|v| v.as_str())
                .map(unseal_secret)
                .unwrap_or_default()
                .trim()
                .to_string();
            if !cloud_key.is_empty() {
                key = cloud_key;
            } else {
                key = self.env_or("GEMINI_API_KEY", "");
            }
        } else if key.is_empty() && prov == "openai" {
            key = self.env_or("OPENAI_API_KEY", "");
        } else if key.is_empty() && prov == "xai" {
            key = self.env_or("XAI_API_KEY", "");
        } else if key.is_empty() && prov == "qwen" {
            key = self.env_or("DASHSCOPE_API_KEY", "");
        }

        let model = lv
            .and_then(|o| o.get("model"))
            .and_then(|v| v.as_str())
            .filter(|v| !v.trim().is_empty())
            .map(|v| v.trim().to_string())
            .unwrap_or_else(|| {
                if prov == "gemini" {
                    self.env_or(
                        "GEMINI_LIVE_MODEL",
                        meta.models.first().map(|s| s.as_str()).unwrap_or("gemini-3.1-flash-live-preview"),
                    )
                } else {
                    meta.models.first().cloned().unwrap_or_default()
                }
            });

        let voice = lv
            .and_then(|o| o.get("voice"))
            .and_then(|v| v.as_str())
            .filter(|v| !v.trim().is_empty())
            .map(|v| v.trim().to_string())
            .unwrap_or_else(|| {
                if prov == "gemini" {
                    let env_v = self.env_or("GEMINI_LIVE_VOICE", "");
                    if !env_v.is_empty() {
                        return env_v;
                    }
                }
                let speaks = self
                    .persona_base
                    .get("speaks")
                    .and_then(|v| v.as_str())
                    .unwrap_or("f");
                if speaks == "m" {
                    meta.voice_m.clone()
                } else {
                    meta.voice_f.clone()
                }
            });

        let url = lv
            .and_then(|o| o.get("url"))
            .and_then(|v| v.as_str())
            .filter(|v| !v.trim().is_empty())
            .map(|v| v.trim().to_string())
            .unwrap_or_else(|| meta.url.clone());

        LiveConfig {
            provider: prov,
            key,
            model,
            voice,
            url,
        }
    }

    pub fn live_ready(&self) -> bool {
        let lv = self.live_config();
        !lv.key.is_empty() && (lv.provider != "custom" || lv.url.starts_with("wss://"))
    }

    pub fn public_live(&self) -> Value {
        let lv = self.live_config();
        let meta = provider_meta(&lv.provider);
        let providers_list: Vec<Value> = live_providers()
            .into_iter()
            .map(|p| {
                json!({
                    "id": p.id,
                    "name": p.name,
                    "free": p.free,
                    "keys": p.keys,
                    "models": p.models,
                    "voices": p.voices,
                    "voice": {"f": p.voice_f, "m": p.voice_m},
                    "note": p.note,
                })
            })
            .collect();
        json!({
            "on": true,
            "ready": self.live_ready(),
            "provider": lv.provider,
            "name": meta.name,
            "model": lv.model,
            "voice": lv.voice,
            "url": lv.url,
            "has_key": !lv.key.is_empty(),
            "own_key": !lv.key.is_empty(),
            "providers": providers_list,
        })
    }

    pub fn is_lite(&self) -> bool {
        if self.lite_mode {
            return true;
        }
        self.load_settings()
            .get("lite_mode")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }

    pub fn speaks(&self) -> String {
        self.persona_base
            .get("speaks")
            .and_then(|v| v.as_str())
            .unwrap_or("f")
            .to_string()
    }

    pub fn version(&self) -> String {
        fs::read_to_string(self.root.join("VERSION"))
            .map(|s| format!("{}-rust-live", s.trim()))
            .unwrap_or_else(|_| "0.10.0-rust-live".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seals_and_unseals_secrets() {
        let plain = "AIzaSyTestSecretKey12345";
        let sealed = seal_secret(plain);
        #[cfg(windows)]
        assert!(sealed.starts_with("dpapi:"));
        assert_eq!(unseal_secret(&sealed), plain);
    }
}

fn parse_env_file(path: &Path) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let Ok(content) = fs::read_to_string(path) else {
        return map;
    };
    for raw_line in content.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let key = k.trim().to_string();
            let val = v
                .trim()
                .trim_matches('"')
                .trim_matches('\'')
                .to_string();
            map.insert(key, val);
        }
    }
    map
}

pub fn find_root(override_root: Option<PathBuf>) -> PathBuf {
    if let Some(r) = override_root {
        return r;
    }
    if let Ok(env_home) = std::env::var("COMPANION_HOME") {
        let p = PathBuf::from(env_home);
        if p.join("web").is_dir() {
            return p;
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.join("web").is_dir() {
            return cwd;
        }
        if let Some(parent) = cwd.parent() {
            if parent.join("web").is_dir() {
                return parent.to_path_buf();
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut cur = exe.parent();
        for _ in 0..5 {
            if let Some(dir) = cur {
                if dir.join("web").is_dir() && dir.join("personas").is_dir() {
                    return dir.to_path_buf();
                }
                cur = dir.parent();
            }
        }
        // Portable standalone mode: store data/ right next to the executable (or %LOCALAPPDATA%\CompanionLive)
        if let Some(exe_dir) = exe.parent() {
            let probe = exe_dir.join(".companion_write_test");
            if fs::write(&probe, b"").is_ok() {
                let _ = fs::remove_file(&probe);
                return exe_dir.to_path_buf();
            }
        }
    }
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        let p = PathBuf::from(local).join("CompanionLive");
        let _ = fs::create_dir_all(&p);
        return p;
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}
