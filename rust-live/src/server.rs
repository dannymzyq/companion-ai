use crate::actions;
use crate::config::{provider_meta, AppConfig};
use crate::desktop_scene;
use crate::models;
use crate::mood::MoodEngine;
use crate::personality;
use crate::session;
use crate::store::MemoryStore;
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Path, Query, State, WebSocketUpgrade};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use chrono::Datelike;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::broadcast;
use tower_http::services::ServeDir;

pub struct AppState {
    pub config: AppConfig,
    pub store: MemoryStore,
    pub mood: MoodEngine,
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

fn origin_ok(headers: &HeaderMap, port: u16) -> bool {
    let Some(origin) = headers.get(header::ORIGIN).and_then(|v| v.to_str().ok()) else {
        return true;
    };
    origin == format!("http://127.0.0.1:{port}")
        || origin == format!("http://localhost:{port}")
        || origin == "null"
}

fn check_origin(headers: &HeaderMap, state: &AppState) -> Result<(), (StatusCode, String)> {
    if origin_ok(headers, state.config.port) {
        Ok(())
    } else {
        Err((StatusCode::FORBIDDEN, "Origen no permitido".into()))
    }
}

pub fn build_router(state: Arc<AppState>) -> Router {
    let web_dir = state.config.web_dir.clone();

    Router::new()
        .route("/api/config", get(get_config).post(set_config))
        .route("/api/setup", get(get_setup).post(set_setup))
        .route("/api/setup/reset", post(reset_setup))
        .route("/api/personality", get(get_personality))
        .route("/api/personality/select", post(select_personality))
        .route("/api/personality/custom", post(save_personality))
        .route("/api/personality/custom/{pid}", delete(delete_personality))
        .route("/api/memory", get(get_memory).delete(delete_all_memory))
        .route("/api/memory/forget", post(forget_fact))
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
        .layer(DefaultBodyLimit::max(models::MAX_MB * 1024 * 1024))
        .fallback_service(ServeDir::new(web_dir))
        .with_state(state)
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
        "presets": [],
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
                    cur.insert("key".into(), json!(k.trim()));
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
                    cur_c.insert("preset".into(), json!("gemini"));
                    cur_c.insert("key".into(), json!(k.trim()));
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
        "ready": true,
        "steps": [
            {"id": "live", "label": "Motor Rust Live listo", "done": true}
        ]
    }))
}

async fn get_update(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(json!({
        "current": state.config.version(),
        "available": false,
        "latest": state.config.version(),
    }))
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
    // Lightweight check against Gemini models endpoint
    let url = format!("https://generativelanguage.googleapis.com/v1beta/models?key={key}");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    match client.get(&url).send().await {
        Ok(resp) if resp.status().is_success() => Ok(Json(json!({"ok": true, "models": ["gemini-3.1-flash-live-preview"]}))),
        Ok(resp) => Ok(Json(json!({"ok": false, "error": format!("Clave rechazada (HTTP {})", resp.status().as_u16())}))),
        Err(e) => Ok(Json(json!({"ok": false, "error": format!("No se pudo comprobar: {e}")}))),
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
