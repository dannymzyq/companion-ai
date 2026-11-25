use crate::actions;
use crate::assets;
use crate::config::{provider_meta, seal_secret, AppConfig};
use crate::desktop_scene;
use crate::models;
use crate::mood::MoodEngine;
use crate::personality;
use crate::session;
use crate::store::MemoryStore;
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Path, Query, Request, State, WebSocketUpgrade};
use axum::http::{header, HeaderMap, StatusCode, Uri};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use chrono::Datelike;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::broadcast;

#[derive(Clone, Default)]
pub struct FocusRuntime {
    pub phase: String, // "idle" | "work" | "break"
    pub end_ts: f64,
    pub streak: u32,
    pub completed_today: u32,
    pub today_str: String,
}

pub struct AppState {
    pub config: AppConfig,
    pub store: MemoryStore,
    pub mood: MoodEngine,
    pub focus: Mutex<FocusRuntime>,
    pub update_cache: Mutex<Option<(Instant, Value)>>,
    pub reset_tx: broadcast::Sender<()>,
    pub shutdown_tx: broadcast::Sender<()>,
}

impl AppState {
    pub fn new(config: AppConfig) -> Arc<Self> {
        let store = MemoryStore::new(&config.data_dir);
        let mood = MoodEngine::new(&config.data_dir);
        let (reset_tx, _) = broadcast::channel(16);
        let (shutdown_tx, _) = broadcast::channel(4);
        Arc::new(Self {
            config,
            store,
            mood,
            focus: Mutex::new(FocusRuntime {
                phase: "idle".into(),
                ..Default::default()
            }),
            update_cache: Mutex::new(None),
            reset_tx,
            shutdown_tx,
        })
    }

    pub fn public_config(&self) -> Value {
        let cfg = &self.config;
        let pers = personality::active(cfg);
        let lv = cfg.live_config();
        let meta = provider_meta(&lv.provider);
        let profile = cfg.user_profile();
        let s = cfg.load_settings();
        let onboarded = s.get("onboarded").and_then(|v| v.as_bool()).unwrap_or(false) || cfg.live_ready();
        let model_id = models::active_id(cfg);
        let model_kind = models::active_kind(cfg);

        json!({
            "rust_live": true,
            "lite_mode": cfg.is_lite(),
            "version": cfg.version(),
            "name": cfg.character_name(),
            "user": profile.name,
            "llm": {
                "provider": "gemini",
                "model": lv.model,
                "name": meta.name,
                "ready": cfg.live_ready(),
                "cloud": true,
                "vision": true,
            },
            "adult": {"active": false},
            "onboarded": onboarded,
            "profile": profile,
            "cloud": {
                "preset": "gemini",
                "name": meta.name,
                "base": "",
                "model": lv.model,
                "has_key": !lv.key.is_empty(),
            },
            "voice": lv.voice,
            "local_model": "",
            "voice_engine": "nube",
            "voice_engine_name": "Voz en vivo (Live API)",
            "voice_engine_pref": "nube",
            "voice_auto": false,
            "voice_reason": "",
            "watch": {"interval": 6, "model": lv.model},
            "stt": {
                "ready": true,
                "device": "live",
                "model": lv.model,
                "error": null,
                "engine": "nube",
                "cloud": {"groq": false, "gemini": !lv.key.is_empty(), "last": null},
                "restart_frees": false,
            },
            "cloud_only": true,
            "gemini_live": true,
            "gemini_live_model": lv.model,
            "gemini_live_voice": lv.voice,
            "live": cfg.public_live(),
            "model": models::active_path(cfg).is_some() || model_kind == "orb",
            "model_id": model_id,
            "model_kind": model_kind,
            "barge_in": cfg.barge_in,
            "actions": actions::public_state(cfg),
            "personality": {
                "id": personality::active_id(cfg),
                "name": pers.get("name").and_then(|v| v.as_str()).unwrap_or("En confianza"),
                "temper": personality::temper(&pers),
            },
            "started": cfg.started,
            "tts": true,
            "gpu": null,
        })
    }

    pub fn personality_state(&self) -> Value {
        let mut p = personality::public(&self.config);
        let active = personality::active(&self.config);
        let base_mood = active
            .get("base_mood")
            .and_then(|v| v.as_str())
            .unwrap_or("neutral");
        if let Some(obj) = p.as_object_mut() {
            obj.insert("mood".into(), self.mood.public(base_mood));
        }
        p
    }
}

pub fn host_ok(headers: &HeaderMap) -> bool {
    let Some(raw) = headers.get(header::HOST).and_then(|v| v.to_str().ok()) else {
        return true;
    };
    let h = raw.trim().to_ascii_lowercase();
    let host_only = h.split(':').next().unwrap_or("");
    matches!(host_only, "127.0.0.1" | "localhost")
}

pub fn origin_ok(headers: &HeaderMap, port: u16) -> bool {
    if !host_ok(headers) {
        return false;
    }
    let Some(origin) = headers.get(header::ORIGIN).and_then(|v| v.to_str().ok()) else {
        return true;
    };
    origin == format!("http://127.0.0.1:{port}") || origin == format!("http://localhost:{port}")
}

fn check_origin(headers: &HeaderMap, state: &AppState) -> Result<(), (StatusCode, String)> {
    if origin_ok(headers, state.config.port) {
        Ok(())
    } else {
        Err((StatusCode::FORBIDDEN, "Origen no permitido".into()))
    }
}

async fn host_guard(req: Request, next: Next) -> Response {
    if !host_ok(req.headers()) {
        return (StatusCode::FORBIDDEN, "Host no permitido").into_response();
    }
    next.run(req).await
}

pub fn build_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/config", get(get_config).post(set_config))
        .route("/api/setup", get(get_setup).post(set_setup))
        .route("/api/setup/reset", post(reset_setup))
        .route("/api/personality", get(get_personality))
        .route("/api/personality/select", post(select_personality))
        .route("/api/personality/custom", post(save_personality))
        .route("/api/personality/custom/{pid}", delete(delete_personality))
        .route("/api/memory", get(get_memory).delete(delete_all_memory))
        .route("/api/memory/diary", get(get_memory_diary))
        .route("/api/memory/item/{mid}", patch(patch_memory_item))
        .route("/api/memory/forget", post(forget_fact))
        .route("/api/backpack", get(export_backpack).post(import_backpack))
        .route("/api/reminders", get(get_reminders))
        .route("/api/focus", get(get_focus).post(set_focus))
        .route("/api/presets", get(get_presets).post(save_preset))
        .route("/api/presets/apply", post(apply_preset))
        .route("/api/presets/{pid}", delete(delete_preset))
        .route("/api/actions", get(get_actions).post(set_actions))
        .route("/api/model", get(get_model_file))
        .route("/api/models", get(list_models).post(upload_model))
        .route("/api/models/select", post(select_model))
        .route("/api/models/{model_id}", delete(delete_model))
        .route("/api/desktop/scene", get(get_desktop_scene))
        .route("/api/loading", get(get_loading))
        .route("/api/update", get(get_update))
        .route("/api/cloud/check", post(cloud_check))
        .route("/api/owner", post(register_owner))
        .route("/api/shutdown", post(shutdown))
        .route("/ws", get(ws_handler))
        .fallback(serve_static)
        .layer(middleware::from_fn(host_guard))
        .layer(DefaultBodyLimit::max(models::MAX_MB * 1024 * 1024))
        .with_state(state)
}

async fn serve_static(State(state): State<Arc<AppState>>, uri: Uri) -> Response {
    let dir = if state.config.web_dir.is_dir() {
        Some(state.config.web_dir.as_path())
    } else {
        None
    };
    assets::serve_web_asset(uri, dir).await
}

async fn get_config(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(state.public_config())
}

async fn set_config(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    if let Some(lite) = body.get("lite_mode").and_then(|v| v.as_bool()) {
        state.config.update_settings(|obj| {
            obj.insert("lite_mode".into(), json!(lite));
        });
    }
    Ok(Json(state.public_config()))
}

async fn get_setup(State(state): State<Arc<AppState>>) -> Json<Value> {
    let cfg = &state.config;
    let lv = cfg.live_config();
    let profile = cfg.user_profile();
    let s = cfg.load_settings();
    let onboarded = s.get("onboarded").and_then(|v| v.as_bool()).unwrap_or(false) || cfg.live_ready();
    let year = chrono::Local::now().year();

    Json(json!({
        "rust_live": true,
        "lite_mode": cfg.is_lite(),
        "resources": {
            "total_gb": 0.0,
            "tier": "live",
            "ear_gb": 0.0,
            "ear_model": "live",
            "desktop_gb": 0.0,
            "room": {"nube": 0.0, "ligera": 0.0, "completa": 0.0},
            "engines": {},
            "recommended_engine": "nube",
            "recommended_model": "",
            "recommended_pair": "nube",
            "best": {},
        },
        "voice_engine": {
            "selected": "nube",
            "in_use": "nube",
            "reason": "",
            "auto": false,
            "recommended": "nube",
            "node": false,
            "fits_now": false,
            "light_installed": false,
            "light_size_mb": 0,
            "light_progress": null,
        },
        "ear": {"engine": "nube", "groq": false, "gemini": !lv.key.is_empty(), "last": null},
        "cloud_only": true,
        "gemini_live": true,
        "gemini_live_model": lv.model,
        "live": cfg.public_live(),
        "onboarded": onboarded,
        "character": cfg.character_name(),
        "year": year,
        "profile": profile,
        "suggested_name": profile.name,
        "provider": "gemini",
        "cloud": {
            "preset": "gemini",
            "name": provider_meta(&lv.provider).name,
            "base": "",
            "model": lv.model,
            "has_key": !lv.key.is_empty(),
        },
        "presets": [
            {
                "id": "gemini",
                "name": "Google Gemini",
                "base": "https://generativelanguage.googleapis.com/v1beta/openai",
                "keys": "https://aistudio.google.com/apikey",
                "note": "Tiene capa gratuita. Recomendado para Live API."
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "base": "https://api.openai.com/v1",
                "keys": "https://platform.openai.com/api-keys",
                "note": "De pago (OpenAI Realtime)."
            },
            {
                "id": "xai",
                "name": "xAI (Grok)",
                "base": "https://api.x.ai/v1",
                "keys": "https://console.x.ai",
                "note": "De pago (Grok Voice)."
            },
            {
                "id": "qwen",
                "name": "Qwen (Alibaba)",
                "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "keys": "https://modelstudio.console.alibabacloud.com",
                "note": "Cuota gratuita inicial."
            },
            {
                "id": "custom",
                "name": "Otro (compatible)",
                "base": "",
                "keys": "",
                "note": "URL personalizada."
            }
        ],
        "local": {"gpu": null, "ollama": false, "recommended": "", "selected": "", "in_use": "", "models": [], "others": []},
        "voices": [],
        "tts": true,
    }))
}

async fn set_setup(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let mut need_reset = false;

    state.config.update_settings(|obj| {
        if let Some(p) = body.get("profile").and_then(|v| v.as_object()) {
            let mut cur = obj
                .get("profile")
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default();
            if let Some(n) = p.get("name").and_then(|v| v.as_str()) {
                let clean: String = n.trim().chars().take(40).collect();
                if !clean.is_empty() {
                    cur.insert("name".into(), json!(clean));
                }
            }
            if let Some(y) = p.get("birth_year").and_then(|v| v.as_i64()) {
                cur.insert("birth_year".into(), json!(y));
            }
            if let Some(g) = p.get("gender").and_then(|v| v.as_str()) {
                cur.insert("gender".into(), json!(g));
            }
            obj.insert("profile".into(), Value::Object(cur));
            need_reset = true;
        }

        if let Some(lv) = body.get("live").and_then(|v| v.as_object()) {
            let mut cur = obj
                .get("live")
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default();
            if let Some(prov) = lv.get("provider").and_then(|v| v.as_str()) {
                cur.insert("provider".into(), json!(prov));
            }
            if lv.get("remove_key").and_then(|v| v.as_bool()).unwrap_or(false) {
                cur.remove("key");
            } else if let Some(k) = lv.get("key").and_then(|v| v.as_str()) {
                if !k.trim().is_empty() {
                    cur.insert("key".into(), json!(seal_secret(k.trim())));
                }
            }
            if let Some(m) = lv.get("model").and_then(|v| v.as_str()) {
                cur.insert("model".into(), json!(m.trim()));
            }
            if let Some(v) = lv.get("voice").and_then(|v| v.as_str()) {
                cur.insert("voice".into(), json!(v.trim()));
            }
            if let Some(u) = lv.get("url").and_then(|v| v.as_str()) {
                cur.insert("url".into(), json!(u.trim()));
            }
            obj.insert("live".into(), Value::Object(cur));
            obj.insert("gemini_live".into(), json!(true));
            need_reset = true;
        }

        if let Some(cl) = body.get("cloud").and_then(|v| v.as_object()) {
            if let Some(k) = cl.get("key").and_then(|v| v.as_str()) {
                if !k.trim().is_empty() {
                    let mut cur_c = obj
                        .get("cloud")
                        .and_then(|v| v.as_object())
                        .cloned()
                        .unwrap_or_default();
                    let preset = cl.get("preset").and_then(|v| v.as_str()).unwrap_or("gemini");
                    cur_c.insert("preset".into(), json!(preset));
                    cur_c.insert("key".into(), json!(seal_secret(k.trim())));
                    obj.insert("cloud".into(), Value::Object(cur_c));
                    need_reset = true;
                }
            }
        }

        if let Some(onb) = body.get("onboarded").and_then(|v| v.as_bool()) {
            obj.insert("onboarded".into(), json!(onb));
        }
        if let Some(lite) = body.get("lite_mode").and_then(|v| v.as_bool()) {
            obj.insert("lite_mode".into(), json!(lite));
        }
    });

    if need_reset {
        let _ = state.reset_tx.send(());
    }
    Ok(Json(state.public_config()))
}

async fn reset_setup(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    state.config.update_settings(|obj| {
        obj.insert("onboarded".into(), json!(false));
    });
    Ok(Json(json!({"ok": true})))
}

async fn get_personality(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(state.personality_state())
}

#[derive(Deserialize)]
struct IdIn {
    id: String,
}

async fn select_personality(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<IdIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    personality::select(&state.config, &body.id).map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    let _ = state.reset_tx.send(());
    Ok(Json(state.personality_state()))
}

async fn save_personality(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    personality::save_custom(&state.config, &body).map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    let _ = state.reset_tx.send(());
    Ok(Json(state.personality_state()))
}

async fn delete_personality(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(pid): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    personality::delete_custom(&state.config, &pid);
    let _ = state.reset_tx.send(());
    Ok(Json(state.personality_state()))
}

async fn get_memory(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(state.store.public_memory())
}

async fn get_memory_diary(
    State(state): State<Arc<AppState>>,
    Query(q): Query<HashMap<String, String>>,
) -> Json<Value> {
    let query = q.get("q").map(|s| s.as_str()).unwrap_or("");
    Json(state.store.diary(query))
}

#[derive(Deserialize)]
struct PatchMemoryIn {
    content: Option<String>,
    pinned: Option<bool>,
}

async fn patch_memory_item(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(mid): Path<u64>,
    Json(body): Json<PatchMemoryIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    if !state.store.update_memory(mid, body.content.as_deref(), body.pinned) {
        return Err((StatusCode::BAD_REQUEST, "Recuerdo no válido o no encontrado".into()));
    }
    Ok(Json(state.store.diary("")))
}

async fn export_backpack(State(state): State<Arc<AppState>>) -> Json<Value> {
    let (memories, summaries) = state.store.export_memories();
    let s = state.config.load_settings();
    let custom_personas = s
        .get("custom_personalities")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let presets = s
        .get("presets")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    Json(json!({
        "schema": "companion-backpack-v1",
        "exported_at": chrono::Local::now().to_rfc3339(),
        "character": state.config.character_name(),
        "profile": state.config.user_profile(),
        "personality_id": personality::active_id(&state.config),
        "custom_personalities": custom_personas,
        "presets": presets,
        "memories": memories,
        "summaries": summaries,
    }))
}

async fn import_backpack(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let schema = body.get("schema").and_then(|v| v.as_str()).unwrap_or("");
    if schema != "companion-backpack-v1" {
        return Err((StatusCode::BAD_REQUEST, "Formato de mochila no reconocido.".into()));
    }
    let merge = body.get("merge").and_then(|v| v.as_bool()).unwrap_or(true);
    if let Some(prof) = body.get("profile").and_then(|v| v.as_object()) {
        state.config.update_settings(|obj| {
            let mut cur = obj
                .get("profile")
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default();
            if let Some(n) = prof.get("name").and_then(|v| v.as_str()) {
                let clean: String = n.trim().chars().take(40).collect();
                if !clean.is_empty() {
                    cur.insert("name".into(), json!(clean));
                }
            }
            if let Some(y) = prof.get("birth_year").and_then(|v| v.as_i64()) {
                cur.insert("birth_year".into(), json!(y));
            }
            if let Some(g) = prof.get("gender").and_then(|v| v.as_str()) {
                cur.insert("gender".into(), json!(g));
            }
            obj.insert("profile".into(), Value::Object(cur));
        });
    }
    if let Some(pid) = body.get("personality_id").and_then(|v| v.as_str()) {
        let _ = personality::select(&state.config, pid);
    }
    let imported = body
        .get("memories")
        .and_then(|v| v.as_array())
        .map(|arr| state.store.import_memories(arr, merge))
        .unwrap_or(0);
    let _ = state.reset_tx.send(());
    Ok(Json(json!({ "ok": true, "imported_memories": imported })))
}

async fn get_reminders() -> Json<Value> {
    Json(json!({ "reminders": [] }))
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn focus_snapshot(rt: &mut FocusRuntime) -> Value {
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    if rt.today_str != today {
        rt.today_str = today;
        rt.completed_today = 0;
    }
    let now = now_secs();
    if (rt.phase == "work" || rt.phase == "break") && now >= rt.end_ts {
        if rt.phase == "work" {
            rt.completed_today += 1;
            if rt.completed_today == 1 {
                rt.streak = rt.streak.saturating_add(1);
            }
        }
        rt.phase = "idle".into();
        rt.end_ts = 0.0;
    }
    let rem = if rt.phase == "idle" {
        0
    } else {
        (rt.end_ts - now).max(0.0).round() as u64
    };
    json!({
        "phase": rt.phase,
        "remaining_sec": rem,
        "streak": rt.streak,
        "completed_today": rt.completed_today,
    })
}

async fn get_focus(State(state): State<Arc<AppState>>) -> Json<Value> {
    let mut guard = state.focus.lock().unwrap();
    Json(focus_snapshot(&mut guard))
}

async fn set_focus(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let action = body.get("action").and_then(|v| v.as_str()).unwrap_or("start");
    let mut guard = state.focus.lock().unwrap();
    let _ = focus_snapshot(&mut guard);
    if action == "stop" {
        guard.phase = "idle".into();
        guard.end_ts = 0.0;
    } else {
        let work_min = body.get("work_min").and_then(|v| v.as_u64()).unwrap_or(25).clamp(1, 180);
        guard.phase = "work".into();
        guard.end_ts = now_secs() + (work_min as f64) * 60.0;
    }
    Ok(Json(focus_snapshot(&mut guard)))
}

async fn get_presets(State(state): State<Arc<AppState>>) -> Json<Value> {
    let s = state.config.load_settings();
    let presets = s.get("presets").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    Json(json!({ "presets": presets }))
}

async fn save_preset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let name: String = body
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("Mi preset")
        .trim()
        .chars()
        .take(48)
        .collect();
    if name.is_empty() {
        return Err((StatusCode::BAD_REQUEST, "Escribe un nombre para el preset.".into()));
    }
    let acc = body.get("accessories").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let lv = state.config.live_config();
    let entry = json!({
        "id": uuid::Uuid::new_v4().to_string()[..8].to_string(),
        "name": name,
        "model_id": models::active_id(&state.config),
        "personality_id": personality::active_id(&state.config),
        "voice": lv.voice,
        "accessories": acc,
    });
    let updated = state.config.update_settings(|obj| {
        let mut list = obj
            .get("presets")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        list.push(entry.clone());
        if list.len() > 24 {
            list.remove(0);
        }
        obj.insert("presets".into(), Value::Array(list));
    });
    let presets = updated.get("presets").cloned().unwrap_or_else(|| json!([]));
    Ok(Json(json!({ "ok": true, "preset": entry, "presets": presets })))
}

async fn apply_preset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<IdIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let s = state.config.load_settings();
    let Some(preset) = s
        .get("presets")
        .and_then(|v| v.as_array())
        .and_then(|arr| arr.iter().find(|p| p.get("id").and_then(|v| v.as_str()) == Some(&body.id)))
        .cloned()
    else {
        return Err((StatusCode::NOT_FOUND, "Preset no encontrado.".into()));
    };
    if let Some(mid) = preset.get("model_id").and_then(|v| v.as_str()) {
        let _ = models::select(&state.config, mid);
    }
    if let Some(pid) = preset.get("personality_id").and_then(|v| v.as_str()) {
        let _ = personality::select(&state.config, pid);
    }
    if let Some(v) = preset.get("voice").and_then(|v| v.as_str()) {
        if !v.is_empty() {
            state.config.update_settings(|obj| {
                let mut lv = obj.get("live").and_then(|x| x.as_object()).cloned().unwrap_or_default();
                lv.insert("voice".into(), json!(v));
                obj.insert("live".into(), Value::Object(lv));
            });
        }
    }
    let _ = state.reset_tx.send(());
    Ok(Json(json!({ "ok": true, "preset": preset })))
}

async fn delete_preset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(pid): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let updated = state.config.update_settings(|obj| {
        let mut list = obj
            .get("presets")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        list.retain(|p| p.get("id").and_then(|v| v.as_str()) != Some(&pid));
        obj.insert("presets".into(), Value::Array(list));
    });
    Ok(Json(json!({ "presets": updated.get("presets").cloned().unwrap_or_else(|| json!([])) })))
}

async fn delete_all_memory(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    state.store.forget_all();
    state.mood.reset();
    let _ = state.reset_tx.send(());
    Ok(Json(json!({"ok": true})))
}

#[derive(Deserialize)]
struct FactIn {
    fact: String,
}

async fn forget_fact(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<FactIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    state.store.delete_memory(&body.fact);
    Ok(Json(state.store.public_memory()))
}

async fn get_actions(State(state): State<Arc<AppState>>) -> Json<Value> {
    let mut st = actions::public_state(&state.config);
    if let Some(obj) = st.as_object_mut() {
        obj.insert("history".into(), json!(actions::history(&state.config, 30)));
    }
    Json(st)
}

#[derive(Deserialize)]
struct ActionsIn {
    enabled: Option<bool>,
    forget_always: Option<String>,
    ask: Option<bool>,
    full: Option<bool>,
}

async fn set_actions(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ActionsIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    actions::save_config(
        &state.config,
        body.enabled,
        body.ask,
        body.full,
        None,
        body.forget_always.as_deref(),
    );
    let _ = state.reset_tx.send(());
    let mut st = actions::public_state(&state.config);
    if let Some(obj) = st.as_object_mut() {
        obj.insert("history".into(), json!(actions::history(&state.config, 30)));
    }
    Ok(Json(st))
}

async fn get_model_file(State(state): State<Arc<AppState>>) -> Response {
    let Some(path) = models::active_path(&state.config) else {
        return (StatusCode::NOT_FOUND, "Sin modelo VRM activo").into_response();
    };
    match tokio::fs::read(&path).await {
        Ok(bytes) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, "model/gltf-binary"),
                (header::CACHE_CONTROL, "no-cache"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => (StatusCode::NOT_FOUND, "Modelo no encontrado").into_response(),
    }
}

async fn list_models(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(models::listing(&state.config))
}

async fn upload_model(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    body: Bytes,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let filename = q.get("filename").map(|s| s.as_str()).unwrap_or("modelo.vrm");
    let saved = models::add_custom(&state.config, filename, &body)
        .map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    let mut out = models::listing(&state.config);
    if let (Some(dst), Some(src)) = (out.as_object_mut(), saved.as_object()) {
        for (k, v) in src {
            dst.insert(k.clone(), v.clone());
        }
    }
    Ok(Json(out))
}

async fn select_model(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<IdIn>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    models::select(&state.config, &body.id).map_err(|e| (StatusCode::NOT_FOUND, e))?;
    Ok(Json(models::listing(&state.config)))
}

async fn delete_model(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(model_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    models::remove_custom(&state.config, &model_id).map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    Ok(Json(models::listing(&state.config)))
}

async fn get_desktop_scene() -> Json<Value> {
    Json(json!({ "fg": desktop_scene::foreground(), "sit": null }))
}

async fn get_loading() -> Json<Value> {
    Json(json!({
        "items": [
            {"id": "live", "label": "Motor Rust Live", "state": "listo", "detail": "listo"}
        ]
    }))
}

fn parse_semver(raw: &str) -> (u32, u32, u32) {
    let clean = raw
        .trim()
        .trim_start_matches('v')
        .split('-')
        .next()
        .unwrap_or("0.0.0");
    let mut parts = clean.split('.').map(|p| p.parse::<u32>().unwrap_or(0));
    (
        parts.next().unwrap_or(0),
        parts.next().unwrap_or(0),
        parts.next().unwrap_or(0),
    )
}

async fn get_update(State(state): State<Arc<AppState>>) -> Json<Value> {
    let current = state.config.version();
    if let Ok(guard) = state.update_cache.lock() {
        if let Some((at, ref cached)) = *guard {
            if at.elapsed().as_secs() < 3600 {
                return Json(cached.clone());
            }
        }
    }
    let fallback = json!({
        "current": current,
        "available": false,
        "latest": current,
    });
    let Ok(client) = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(4))
        .user_agent("companion-live")
        .build()
    else {
        return Json(fallback);
    };
    let resp = match client
        .get("https://api.github.com/repos/dannymzyq/companion-ai/releases/latest")
        .send()
        .await
    {
        Ok(r) if r.status().is_success() => r,
        _ => return Json(fallback),
    };
    let Ok(data) = resp.json::<Value>().await else {
        return Json(fallback);
    };
    let tag = data
        .get("tag_name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if tag.is_empty() {
        return Json(fallback);
    }
    let available = parse_semver(tag) > parse_semver(&current);
    let url = data
        .get("html_url")
        .and_then(|v| v.as_str())
        .unwrap_or("https://github.com/dannymzyq/companion-ai/releases/latest");
    let out = json!({
        "current": current,
        "available": available,
        "latest": tag.trim_start_matches('v'),
        "url": url,
    });
    if let Ok(mut guard) = state.update_cache.lock() {
        *guard = Some((Instant::now(), out.clone()));
    }
    Json(out)
}

async fn cloud_check(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let key = body.get("key").and_then(|v| v.as_str()).unwrap_or("").trim();
    if key.is_empty() {
        return Ok(Json(json!({"ok": false, "error": "Escribe tu clave API."})));
    }
    let preset = body
        .get("preset")
        .or_else(|| body.get("provider"))
        .and_then(|v| v.as_str())
        .unwrap_or("gemini")
        .trim()
        .to_ascii_lowercase();

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let req = if preset == "gemini" || (preset.is_empty() && key.starts_with("AIza")) {
        client
            .get("https://generativelanguage.googleapis.com/v1beta/models")
            .header("x-goog-api-key", key)
    } else {
        let base = match preset.as_str() {
            "openai" => "https://api.openai.com/v1".to_string(),
            "xai" => "https://api.x.ai/v1".to_string(),
            "qwen" => "https://dashscope-intl.aliyuncs.com/compatible-mode/v1".to_string(),
            _ => {
                let raw_b = body.get("base").and_then(|v| v.as_str()).unwrap_or("").trim();
                let b = raw_b.trim_end_matches('/');
                let ok_scheme = b.starts_with("https://")
                    || b.starts_with("http://127.0.0.1")
                    || b.starts_with("http://localhost");
                if !ok_scheme {
                    return Ok(Json(json!({"ok": false, "error": "URL base inválida (usa https://)."})));
                }
                b.to_string()
            }
        };
        client
            .get(format!("{base}/models"))
            .header("Authorization", format!("Bearer {key}"))
    };

    match req.send().await {
        Ok(resp) if resp.status().is_success() => {
            let meta = provider_meta(&preset);
            Ok(Json(json!({"ok": true, "models": meta.models})))
        }
        Ok(resp) => Ok(Json(json!({"ok": false, "error": format!("Clave rechazada (HTTP {})", resp.status().as_u16())}))),
        Err(e) => {
            let clean = crate::live::sanitize_secret(&e.to_string(), key);
            Ok(Json(json!({"ok": false, "error": format!("No se pudo comprobar: {clean}")})))
        }
    }
}

async fn register_owner() -> Json<Value> {
    Json(json!({"ok": true}))
}

async fn shutdown(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_origin(&headers, &state)?;
    let _ = state.shutdown_tx.send(());
    Ok(Json(json!({"ok": true})))
}

async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Response {
    if !origin_ok(&headers, state.config.port) {
        return StatusCode::FORBIDDEN.into_response();
    }
    ws.on_upgrade(move |socket| session::run_ws_session(socket, state))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn enforces_host_and_origin_headers() {
        let mut h = HeaderMap::new();
        h.insert(header::HOST, HeaderValue::from_static("127.0.0.1:8200"));
        assert!(host_ok(&h));
        assert!(origin_ok(&h, 8200));

        h.insert(header::ORIGIN, HeaderValue::from_static("null"));
        assert!(!origin_ok(&h, 8200));

        let mut evil = HeaderMap::new();
        evil.insert(header::HOST, HeaderValue::from_static("evil.rebind.attacker.com:8200"));
        assert!(!host_ok(&evil));
        assert!(!origin_ok(&evil, 8200));
    }

    #[test]
    fn compares_semver_cleanly() {
        assert!(parse_semver("v0.11.0") > parse_semver("0.10.0-rust-live"));
        assert!(!(parse_semver("v0.10.0") > parse_semver("0.10.0-rust-live")));
    }
}
