use crate::config::{provider_meta, LiveConfig};
use crate::prompt::{EMOTIONS, GESTURES};
use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use futures_util::stream::SplitSink;
use futures_util::{SinkExt, StreamExt};
use regex::Regex;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::OnceLock;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{connect_async, MaybeTlsStream, WebSocketStream};

pub const INPUT_RATE: u32 = 16000;
pub const OUTPUT_RATE: u32 = 24000;

#[derive(Debug, Clone)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub args: Value,
}

#[derive(Debug, Clone)]
pub enum LiveEvent {
    Audio(Vec<u8>),
    InText(String),
    OutText(String),
    ToolCall(Vec<ToolCall>),
    Interrupted,
    TurnComplete,
    Closed(Option<String>),
}

#[derive(Debug)]
pub enum LiveCmd {
    Audio(Vec<u8>),
    Image(String),
    Text { text: String, images: Vec<String> },
    ToolResponse(Vec<Value>),
    Close,
}

pub struct LiveHandle {
    pub tx: mpsc::Sender<LiveCmd>,
}

impl LiveHandle {
    pub async fn send_audio(&self, pcm: Vec<u8>) -> bool {
        self.tx.send(LiveCmd::Audio(pcm)).await.is_ok()
    }
    pub async fn send_image(&self, jpeg_b64: String) -> bool {
        self.tx.send(LiveCmd::Image(jpeg_b64)).await.is_ok()
    }
    pub async fn send_text(&self, text: String, images: Vec<String>) -> bool {
        self.tx.send(LiveCmd::Text { text, images }).await.is_ok()
    }
    pub async fn send_tool_response(&self, responses: Vec<Value>) -> bool {
        self.tx.send(LiveCmd::ToolResponse(responses)).await.is_ok()
    }
    pub async fn close(&self) {
        let _ = self.tx.send(LiveCmd::Close).await;
    }
}

pub fn clean_spoken_text(text: &str) -> String {
    static TAG_RE: OnceLock<Regex> = OnceLock::new();
    let re = TAG_RE.get_or_init(|| Regex::new(r"\[[^\]]+\]").unwrap());
    re.replace_all(text, "").trim().to_string()
}

pub fn guess_emotion(text: &str) -> Option<&'static str> {
    static RES: OnceLock<Vec<(&'static str, Regex)>> = OnceLock::new();
    let list = RES.get_or_init(|| {
        let raw = [
            ("triste", r"(?i)lo siento|qu[eé] pena|qu[eé] triste|qu[eé] mal|\bpobre|lamento|\bánimo"),
            ("molesta", r"(?i)\boye\b|qu[eé] pesad|no me gusta|me molesta|ya basta|qu[eé] rabia"),
            ("sorprendida", r"(?i)\bwow\b|en serio\?|de verdad\?|no me digas|no puede ser"),
            ("emocionada", r"(?i)qu[eé] emoci[oó]n|incre[ií]ble|felicidades|enhorabuena|me encanta|\bgenial\b"),
            ("sonrojada", r"(?i)me sonroj|qu[eé] cosas dices|ay,? (calla|para)"),
            ("carinosa", r"(?i)cari[nñ]o|aqu[ií] estoy|te quiero|mi vida|\babrazo"),
            ("feliz", r"(?i)\bjaj|\bjej|qu[eé] bien|me alegra|\bbonito|claro que s[ií]"),
            ("pensativa", r"(?i)\bhmm|d[eé]jame pensar|\ba ver\b|buena pregunta"),
            ("confundida", r"(?i)no entiendo|\bc[oó]mo\?|\bqu[eé] dices"),
            ("nerviosa", r"(?i)\beh+\.\.\.|\bum+\b|\bbueno\.\.\."),
        ];
        raw.into_iter().map(|(e, rx)| (e, Regex::new(rx).unwrap())).collect()
    });
    for (emo, re) in list {
        if re.is_match(text) {
            return Some(*emo);
        }
    }
    None
}

pub fn resample_pcm16(pcm: &[u8], src_rate: u32, dst_rate: u32) -> Vec<u8> {
    if src_rate == dst_rate || pcm.len() < 2 {
        return pcm.to_vec();
    }
    let samples: Vec<f32> = pcm
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]) as f32)
        .collect();
    if samples.is_empty() {
        return vec![];
    }
    let out_len = ((samples.len() as f64) * (dst_rate as f64) / (src_rate as f64)) as usize;
    if out_len == 0 {
        return vec![];
    }
    let mut out = Vec::with_capacity(out_len * 2);
    let max_idx = (samples.len() - 1) as f64;
    let denom = (out_len.saturating_sub(1)).max(1) as f64;
    for i in 0..out_len {
        let pos = (i as f64) * max_idx / denom;
        let idx = pos.floor() as usize;
        let frac = (pos - idx as f64) as f32;
        let s0 = samples[idx];
        let s1 = samples[(idx + 1).min(samples.len() - 1)];
        let val = (s0 + (s1 - s0) * frac).clamp(-32768.0, 32767.0) as i16;
        out.extend_from_slice(&val.to_le_bytes());
    }
    out
}

fn express_tool_gemini() -> Value {
    let mut gestures = vec!["ninguno"];
    gestures.extend_from_slice(GESTURES);
    json!({
        "name": "expresar",
        "behavior": "NON_BLOCKING",
        "description": "Muestra en tu cara y tu cuerpo la emoción que sientes y, si viene a cuento, un gesto. Llámala al empezar cada respuesta. No hace falta esperar su resultado.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "emocion": {"type": "STRING", "enum": EMOTIONS},
                "gesto": {"type": "STRING", "enum": gestures},
            },
            "required": ["emocion"],
        }
    })
}

fn remember_tool_gemini() -> Value {
    json!({
        "name": "recordar",
        "behavior": "NON_BLOCKING",
        "description": "Guarda un dato duradero importante sobre el usuario (gustos, proyectos, mascotas, cumpleaños, nombre) para recordarlo en futuras conversaciones.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "dato": {"type": "STRING", "description": "Frase breve y clara sobre el usuario."}
            },
            "required": ["dato"],
        }
    })
}

fn action_tool_gemini() -> Value {
    json!({
        "name": "ejecutar_accion",
        "description": "Ejecuta una acción segura en la PC del usuario: abrir una aplicación, abrir una web o carpeta, buscar archivos, poner un temporizador o controlar volumen/multimedia.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "accion": {
                    "type": "STRING",
                    "description": "Tipo: 'abrir_app', 'abrir_web', 'abrir_carpeta', 'buscar_archivo', 'temporizador', 'multimedia' o 'volumen'."
                },
                "arg1": {
                    "type": "STRING",
                    "description": "Argumento principal: app, URL o búsqueda, carpeta, archivo, duración ('10m'), multimedia ('pausa'|'siguiente'|'anterior') o volumen ('subir'|'bajar'|'silenciar')."
                },
                "arg2": {
                    "type": "STRING",
                    "description": "Opcional. Para 'temporizador': etiqueta."
                }
            },
            "required": ["accion", "arg1"],
        }
    })
}

fn lowercase_types(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, val) in map {
                if k == "type" {
                    if let Some(s) = val.as_str() {
                        out.insert(k.clone(), Value::String(s.to_lowercase()));
                        continue;
                    }
                }
                out.insert(k.clone(), lowercase_types(val));
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(lowercase_types).collect()),
        other => other.clone(),
    }
}

fn tools_for_realtime(actions_enabled: bool) -> Vec<Value> {
    let mut raw = vec![express_tool_gemini(), remember_tool_gemini()];
    if actions_enabled {
        raw.push(action_tool_gemini());
    }
    raw.into_iter()
        .map(|t| {
            json!({
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": lowercase_types(&t["parameters"]),
            })
        })
        .collect()
}

pub async fn connect_live(
    cfg: LiveConfig,
    system_instruction: String,
    temperature: f64,
    actions_enabled: bool,
) -> Result<(LiveHandle, mpsc::Receiver<LiveEvent>), String> {
    if cfg.key.is_empty() {
        return Err(format!(
            "Falta la clave de API de {}. Configúrala en Ajustes.",
            provider_meta(&cfg.provider).name
        ));
    }
    if cfg.provider == "gemini" {
        connect_gemini(cfg, system_instruction, temperature, actions_enabled).await
    } else {
        connect_realtime(cfg, system_instruction, temperature, actions_enabled).await
    }
}

async fn connect_gemini(
    cfg: LiveConfig,
    system_instruction: String,
    temperature: f64,
    actions_enabled: bool,
) -> Result<(LiveHandle, mpsc::Receiver<LiveEvent>), String> {
    let model = if cfg.model.starts_with("models/") {
        cfg.model.clone()
    } else {
        format!("models/{}", cfg.model)
    };
    let endpoint = format!("{}?key={}", provider_meta("gemini").url, cfg.key);

    let (ws, _) = tokio::time::timeout(std::time::Duration::from_secs(15), connect_async(&endpoint))
        .await
        .map_err(|_| "Tiempo agotado conectando con Gemini Live.".to_string())?
        .map_err(|e| format!("No se pudo conectar a Gemini Live: {e}"))?;

    let (mut sink, mut stream) = ws.split();

    let mut decls = vec![express_tool_gemini(), remember_tool_gemini()];
    if actions_enabled {
        decls.push(action_tool_gemini());
    }

    let setup = json!({
        "setup": {
            "model": model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "temperature": temperature,
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": { "voiceName": cfg.voice }
                    }
                }
            },
            "systemInstruction": {
                "parts": [{ "text": system_instruction }]
            },
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            "tools": [{ "functionDeclarations": decls }],
        }
    });

    sink.send(Message::Text(setup.to_string().into()))
        .await
        .map_err(|e| format!("Error enviando setup a Gemini Live: {e}"))?;

    // Wait for setupComplete
    let first = tokio::time::timeout(std::time::Duration::from_secs(15), stream.next())
        .await
        .map_err(|_| "Gemini Live no respondió al setup a tiempo.".to_string())?
        .ok_or_else(|| "Gemini Live cerró la conexión al iniciar.".to_string())?
        .map_err(|e| format!("Error leyendo respuesta inicial de Gemini Live: {e}"))?;

    let first_txt = match first {
        Message::Text(t) => t.to_string(),
        Message::Binary(b) => String::from_utf8_lossy(&b).to_string(),
        Message::Close(f) => {
            return Err(format!("Gemini Live cerró la conexión: {:?}", f));
        }
        _ => String::new(),
    };
    let first_json: Value = serde_json::from_str(&first_txt).unwrap_or(Value::Null);
    if first_json.get("setupComplete").is_none() {
        return Err(format!(
            "Gemini Live rechazó la configuración inicial: {}",
            first_txt.chars().take(240).collect::<String>()
        ));
    }

    let (cmd_tx, mut cmd_rx) = mpsc::channel::<LiveCmd>(128);
    let (ev_tx, ev_rx) = mpsc::channel::<LiveEvent>(256);

    tokio::spawn(async move {
        let mut ws_sink: SplitSink<WebSocketStream<MaybeTlsStream<TcpStream>>, Message> = sink;
        let ev_tx_read = ev_tx.clone();

        let reader = tokio::spawn(async move {
            while let Some(item) = stream.next().await {
                let raw = match item {
                    Ok(Message::Text(t)) => t.to_string(),
                    Ok(Message::Binary(b)) => String::from_utf8_lossy(&b).to_string(),
                    Ok(Message::Close(_)) => break,
                    Ok(_) => continue,
                    Err(e) => {
                        let _ = ev_tx_read.send(LiveEvent::Closed(Some(e.to_string()))).await;
                        return;
                    }
                };
                let Ok(msg) = serde_json::from_str::<Value>(&raw) else {
                    continue;
                };
                if let Some(calls) = msg
                    .get("toolCall")
                    .and_then(|tc| tc.get("functionCalls"))
                    .and_then(|v| v.as_array())
                {
                    let parsed: Vec<ToolCall> = calls
                        .iter()
                        .map(|fc| ToolCall {
                            id: fc.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            name: fc.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            args: fc.get("args").cloned().unwrap_or_else(|| json!({})),
                        })
                        .collect();
                    if !parsed.is_empty() {
                        let _ = ev_tx_read.send(LiveEvent::ToolCall(parsed)).await;
                    }
                }
                if let Some(sc) = msg.get("serverContent").and_then(|v| v.as_object()) {
                    if sc.get("interrupted").and_then(|v| v.as_bool()).unwrap_or(false) {
                        let _ = ev_tx_read.send(LiveEvent::Interrupted).await;
                    }
                    if let Some(txt) = sc
                        .get("inputTranscription")
                        .and_then(|t| t.get("text"))
                        .and_then(|v| v.as_str())
                    {
                        if !txt.is_empty() {
                            let _ = ev_tx_read.send(LiveEvent::InText(txt.to_string())).await;
                        }
                    }
                    if let Some(txt) = sc
                        .get("outputTranscription")
                        .and_then(|t| t.get("text"))
                        .and_then(|v| v.as_str())
                    {
                        if !txt.is_empty() {
                            let _ = ev_tx_read.send(LiveEvent::OutText(txt.to_string())).await;
                        }
                    }
                    if let Some(parts) = sc
                        .get("modelTurn")
                        .and_then(|mt| mt.get("parts"))
                        .and_then(|v| v.as_array())
                    {
                        for part in parts {
                            if let Some(inline) = part.get("inlineData").and_then(|v| v.as_object()) {
                                let mime = inline.get("mimeType").and_then(|v| v.as_str()).unwrap_or("");
                                if mime.is_empty() || mime.starts_with("audio/pcm") {
                                    if let Some(b64) = inline.get("data").and_then(|v| v.as_str()) {
                                        if let Ok(bytes) = B64.decode(b64) {
                                            let _ = ev_tx_read.send(LiveEvent::Audio(bytes)).await;
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if sc.get("turnComplete").and_then(|v| v.as_bool()).unwrap_or(false) {
                        let _ = ev_tx_read.send(LiveEvent::TurnComplete).await;
                    }
                }
            }
            let _ = ev_tx_read.send(LiveEvent::Closed(None)).await;
        });

        while let Some(cmd) = cmd_rx.recv().await {
            let payload = match cmd {
                LiveCmd::Audio(pcm) => json!({
                    "realtimeInput": {
                        "audio": {
                            "mimeType": format!("audio/pcm;rate={INPUT_RATE}"),
                            "data": B64.encode(pcm),
                        }
                    }
                }),
                LiveCmd::Image(jpeg) => json!({
                    "realtimeInput": {
                        "video": {
                            "mimeType": "image/jpeg",
                            "data": jpeg,
                        }
                    }
                }),
                LiveCmd::Text { text, images } => {
                    let mut parts: Vec<Value> = images
                        .into_iter()
                        .filter(|i| !i.is_empty())
                        .map(|img| json!({"inlineData": {"mimeType": "image/jpeg", "data": img}}))
                        .collect();
                    parts.push(json!({"text": text}));
                    json!({
                        "clientContent": {
                            "turns": [{"role": "user", "parts": parts}],
                            "turnComplete": true,
                        }
                    })
                }
                LiveCmd::ToolResponse(responses) => {
                    let out: Vec<Value> = responses
                        .into_iter()
                        .map(|mut r| {
                            if matches!(r.get("name").and_then(|v| v.as_str()), Some("expresar" | "recordar")) {
                                if let Some(resp) = r.get_mut("response").and_then(|v| v.as_object_mut()) {
                                    resp.insert("scheduling".into(), json!("SILENT"));
                                }
                            }
                            r
                        })
                        .collect();
                    json!({ "toolResponse": { "functionResponses": out } })
                }
                LiveCmd::Close => {
                    let _ = ws_sink.close().await;
                    break;
                }
            };
            if ws_sink.send(Message::Text(payload.to_string().into())).await.is_err() {
                break;
            }
        }
        reader.abort();
    });

    Ok((LiveHandle { tx: cmd_tx }, ev_rx))
}

async fn connect_realtime(
    cfg: LiveConfig,
    system_instruction: String,
    temperature: f64,
    actions_enabled: bool,
) -> Result<(LiveHandle, mpsc::Receiver<LiveEvent>), String> {
    let meta = provider_meta(&cfg.provider);
    if !cfg.url.starts_with("wss://") {
        return Err("Falta la dirección wss:// del proveedor en vivo.".into());
    }
    let full_url = if cfg.url.contains("model=") || cfg.model.is_empty() {
        cfg.url.clone()
    } else if cfg.url.contains('?') {
        format!("{}&model={}", cfg.url, cfg.model)
    } else {
        format!("{}?model={}", cfg.url, cfg.model)
    };

    let mut req = full_url
        .into_client_request()
        .map_err(|e| format!("URL inválida: {e}"))?;
    req.headers_mut().insert(
        "Authorization",
        format!("Bearer {}", cfg.key)
            .parse()
            .map_err(|_| "Clave API inválida".to_string())?,
    );

    let (ws, _) = tokio::time::timeout(std::time::Duration::from_secs(15), connect_async(req))
        .await
        .map_err(|_| format!("Tiempo agotado conectando con {}.", meta.name))?
        .map_err(|e| format!("No se pudo conectar a {}: {e}", meta.name))?;

    let (mut sink, mut stream) = ws.split();
    let tools = tools_for_realtime(actions_enabled);
    let flavor = meta.flavor.clone();
    let rate = meta.rate;

    let session_cfg = if flavor == "ga" {
        json!({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": cfg.model,
                "instructions": system_instruction,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": rate},
                        "transcription": {"model": "gpt-4o-mini-transcribe", "language": "es"},
                        "turn_detection": {"type": "server_vad", "interrupt_response": true},
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": OUTPUT_RATE},
                        "voice": cfg.voice,
                    }
                },
                "tools": tools,
                "tool_choice": "auto",
            }
        })
    } else {
        let mut s = json!({
            "modalities": ["text", "audio"],
            "instructions": system_instruction,
            "voice": cfg.voice,
            "input_audio_format": "pcm16",
            "output_audio_format": meta.out_format,
            "input_audio_transcription": {"model": if cfg.provider == "qwen" { "gummy-realtime-v1" } else { "whisper-1" }},
            "turn_detection": {"type": "server_vad"},
            "tools": tools,
            "tool_choice": "auto",
        });
        if cfg.provider != "qwen" {
            s["temperature"] = json!(temperature.clamp(0.6, 1.2));
        }
        json!({ "type": "session.update", "session": s })
    };

    sink.send(Message::Text(session_cfg.to_string().into()))
        .await
        .map_err(|e| format!("Error enviando session.update: {e}"))?;

    let (cmd_tx, mut cmd_rx) = mpsc::channel::<LiveCmd>(128);
    let (ev_tx, ev_rx) = mpsc::channel::<LiveEvent>(256);

    tokio::spawn(async move {
        let ev_tx_read = ev_tx.clone();
        let reader = tokio::spawn(async move {
            let mut pending_calls: HashMap<String, (String, String)> = HashMap::new();
            while let Some(item) = stream.next().await {
                let raw = match item {
                    Ok(Message::Text(t)) => t.to_string(),
                    Ok(Message::Binary(b)) => String::from_utf8_lossy(&b).to_string(),
                    Ok(Message::Close(_)) => break,
                    Ok(_) => continue,
                    Err(e) => {
                        let _ = ev_tx_read.send(LiveEvent::Closed(Some(e.to_string()))).await;
                        return;
                    }
                };
                let Ok(msg) = serde_json::from_str::<Value>(&raw) else { continue };
                let kind = msg.get("type").and_then(|v| v.as_str()).unwrap_or("");
                match kind {
                    "response.audio.delta" | "response.output_audio.delta" => {
                        if let Some(b64) = msg.get("delta").and_then(|v| v.as_str()) {
                            if let Ok(bytes) = B64.decode(b64) {
                                let _ = ev_tx_read.send(LiveEvent::Audio(bytes)).await;
                            }
                        }
                    }
                    "response.audio_transcript.delta" | "response.output_audio_transcript.delta" => {
                        if let Some(d) = msg.get("delta").and_then(|v| v.as_str()) {
                            if !d.is_empty() {
                                let _ = ev_tx_read.send(LiveEvent::OutText(d.to_string())).await;
                            }
                        }
                    }
                    "conversation.item.input_audio_transcription.completed" => {
                        if let Some(t) = msg.get("transcript").and_then(|v| v.as_str()) {
                            if !t.is_empty() {
                                let _ = ev_tx_read.send(LiveEvent::InText(t.to_string())).await;
                            }
                        }
                    }
                    "input_audio_buffer.speech_started" => {
                        let _ = ev_tx_read.send(LiveEvent::Interrupted).await;
                    }
                    "response.function_call_arguments.delta" => {
                        let cid = msg.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let delta = msg.get("delta").and_then(|v| v.as_str()).unwrap_or("");
                        let entry = pending_calls.entry(cid).or_insert_with(|| (String::new(), String::new()));
                        entry.1.push_str(delta);
                    }
                    "response.output_item.added" => {
                        if let Some(item) = msg.get("item") {
                            if item.get("type").and_then(|v| v.as_str()) == Some("function_call") {
                                let cid = item.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let name = item.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                pending_calls.insert(cid, (name, String::new()));
                            }
                        }
                    }
                    "response.function_call_arguments.done" => {
                        let cid = msg.get("call_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let name = msg
                            .get("name")
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string())
                            .or_else(|| pending_calls.get(&cid).map(|(n, _)| n.clone()))
                            .unwrap_or_default();
                        let args_str = msg
                            .get("arguments")
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string())
                            .or_else(|| pending_calls.remove(&cid).map(|(_, a)| a))
                            .unwrap_or_else(|| "{}".to_string());
                        let args = serde_json::from_str::<Value>(&args_str).unwrap_or_else(|_| json!({}));
                        let _ = ev_tx_read
                            .send(LiveEvent::ToolCall(vec![ToolCall { id: cid, name, args }]))
                            .await;
                    }
                    "response.done" => {
                        let _ = ev_tx_read.send(LiveEvent::TurnComplete).await;
                    }
                    _ => {}
                }
            }
            let _ = ev_tx_read.send(LiveEvent::Closed(None)).await;
        });

        while let Some(cmd) = cmd_rx.recv().await {
            match cmd {
                LiveCmd::Audio(pcm) => {
                    let resampled = resample_pcm16(&pcm, INPUT_RATE, rate);
                    let msg = json!({
                        "type": "input_audio_buffer.append",
                        "audio": B64.encode(resampled),
                    });
                    if sink.send(Message::Text(msg.to_string().into())).await.is_err() {
                        break;
                    }
                }
                LiveCmd::Image(jpeg) => {
                    let msg = json!({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_image", "image_url": format!("data:image/jpeg;base64,{jpeg}")}]
                        }
                    });
                    let _ = sink.send(Message::Text(msg.to_string().into())).await;
                }
                LiveCmd::Text { text, images } => {
                    let mut content: Vec<Value> = images
                        .into_iter()
                        .filter(|i| !i.is_empty())
                        .map(|img| json!({"type": "input_image", "image_url": format!("data:image/jpeg;base64,{img}")}))
                        .collect();
                    content.push(json!({"type": "input_text", "text": text}));
                    let item = json!({
                        "type": "conversation.item.create",
                        "item": {"type": "message", "role": "user", "content": content}
                    });
                    let resp = json!({"type": "response.create"});
                    if sink.send(Message::Text(item.to_string().into())).await.is_err()
                        || sink.send(Message::Text(resp.to_string().into())).await.is_err()
                    {
                        break;
                    }
                }
                LiveCmd::ToolResponse(responses) => {
                    let mut need_reply = false;
                    for r in responses {
                        let cid = r.get("id").and_then(|v| v.as_str()).unwrap_or("");
                        let name = r.get("name").and_then(|v| v.as_str()).unwrap_or("");
                        if !matches!(name, "expresar" | "recordar") {
                            need_reply = true;
                        }
                        let output = serde_json::to_string(&r["response"]).unwrap_or_else(|_| "{}".into());
                        let msg = json!({
                            "type": "conversation.item.create",
                            "item": {"type": "function_call_output", "call_id": cid, "output": output}
                        });
                        let _ = sink.send(Message::Text(msg.to_string().into())).await;
                    }
                    if need_reply {
                        let _ = sink.send(Message::Text(json!({"type": "response.create"}).to_string().into())).await;
                    }
                }
                LiveCmd::Close => {
                    let _ = sink.close().await;
                    break;
                }
            }
        }
        reader.abort();
    });

    Ok((LiveHandle { tx: cmd_tx }, ev_rx))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resamples_16k_to_24k() {
        let pcm: Vec<u8> = (0..160i16).flat_map(|i| (i * 100).to_le_bytes()).collect();
        let out = resample_pcm16(&pcm, 16000, 24000);
        assert_eq!(out.len(), 240 * 2);
    }

    #[test]
    fn cleans_tags_and_guesses_emotion() {
        assert_eq!(clean_spoken_text("[emo:feliz] ¡Hola!"), "¡Hola!");
        assert_eq!(guess_emotion("¡Qué alegría me da verte! jaja"), Some("feliz"));
        assert_eq!(guess_emotion("Lo siento mucho, qué pena"), Some("triste"));
    }
}
