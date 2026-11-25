use crate::actions::{self, PreparedAction};
use crate::live::{clean_spoken_text, connect_live, guess_emotion, LiveEvent, LiveHandle};
use crate::mood;
use crate::personality;
use crate::play::{self, plain};
use crate::prompt::{build_live_system_prompt, temperature_for, EMOTIONS, GESTURES};
use crate::server::AppState;
use axum::extract::ws::{Message, WebSocket};
use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::mpsc;

const GREETING: &str = "(Acaba de abrirse la conversación. Saluda al usuario de forma breve y natural, como lo harías tú.)";
const FRAME_MAX_AGE_SECS: f64 = 15.0;

struct FrameEntry {
    jpeg: String,
    at: Instant,
}

enum InternalMsg {
    Live(LiveEvent),
    TimerDone { label: String, secs: u64 },
    PttState(bool),
}

#[cfg(windows)]
fn ptt_vk(key: &str) -> i32 {
    match key {
        "F9" => 0x78,
        "F8" => 0x77,
        "CapsLock" => 0x14,
        "ControlRight" => 0xA3,
        _ => 0xA5, // AltRight (VK_RMENU)
    }
}

fn pick_rps_choice() -> &'static str {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    match nanos % 3 {
        0 => "piedra",
        1 => "papel",
        _ => "tijera",
    }
}

pub async fn run_ws_session(socket: WebSocket, state: Arc<AppState>) {
    let (mut ws_sink, mut ws_stream) = socket.split();
    let (out_tx, mut out_rx) = mpsc::channel::<Message>(256);

    let writer = tokio::spawn(async move {
        while let Some(msg) = out_rx.recv().await {
            if ws_sink.send(msg).await.is_err() {
                break;
            }
        }
    });

    // Send hello
    let mut hello = state.public_config();
    if let Some(obj) = hello.as_object_mut() {
        obj.insert("type".into(), json!("hello"));
    }
    let _ = out_tx.send(Message::Text(hello.to_string().into())).await;

    let mut live_handle: Option<LiveHandle> = None;
    let (int_tx, mut int_rx) = mpsc::channel::<InternalMsg>(256);
    let mut reset_rx = state.reset_tx.subscribe();

    let mut cur_state = String::from("idle");
    let mut emotion = String::from("neutral");
    let mut client_playing = false;
    let mut turn_open = false;
    let mut sentence_id: u64 = 0;
    let mut live_user = false;
    let mut live_emo = String::new();
    let mut live_gesture: Option<String> = None;
    let mut pcm_buf: Vec<u8> = Vec::with_capacity(4096);
    let mut in_buf = String::new();
    let mut out_buf = String::new();
    let mut frames: HashMap<String, FrameEntry> = HashMap::new();
    let mut last_frame_sent = Instant::now() - std::time::Duration::from_secs(5);
    let mut pending_actions: HashMap<String, PreparedAction> = HashMap::new();
    let mut resume_handle: Option<String> = None;
    let mut go_away_pending = false;
    let mut live_mixed_at: Option<Instant> = None;
    let mut ptt_task: Option<tokio::task::JoinHandle<()>> = None;
    let mut game_mode: Option<String> = None;

    let send_json = |tx: &mpsc::Sender<Message>, val: Value| {
        let _ = tx.try_send(Message::Text(val.to_string().into()));
    };

    let set_state = |cur: &mut String, next: &str, tx: &mpsc::Sender<Message>| {
        if cur != next {
            *cur = next.to_string();
            let _ = tx.try_send(Message::Text(json!({"type": "state", "value": next}).to_string().into()));
        }
    };

    async fn ensure_live(
        live_handle: &mut Option<LiveHandle>,
        state: &Arc<AppState>,
        int_tx: &mpsc::Sender<InternalMsg>,
        out_tx: &mpsc::Sender<Message>,
        cur_state: &mut String,
        resume_handle: &mut Option<String>,
        frames: &HashMap<String, FrameEntry>,
    ) -> bool {
        if live_handle.is_some() {
            return true;
        }
        let cfg = &state.config;
        let lv = cfg.live_config();
        let pers = personality::active(cfg);
        let base_mood = pers.get("base_mood").and_then(|v| v.as_str()).unwrap_or("neutral");
        let speaks = cfg.speaks();
        let mood_desc = state.mood.describe_for(base_mood, &speaks);
        let gap = mood::since_last_talk(state.store.previous_ts());
        let memories = state.store.memories(40);
        let recent: Vec<(String, String)> = state
            .store
            .recent_messages(14)
            .into_iter()
            .map(|m| (m.role, m.text))
            .collect();
        let system = build_live_system_prompt(cfg, &pers, &memories, &recent, &mood_desc, &gap);
        let temp = temperature_for(&pers);
        let actions_on = actions::get_config(cfg).enabled;

        let mut res = connect_live(lv.clone(), system.clone(), temp, actions_on, resume_handle.clone()).await;
        if res.is_err() && resume_handle.is_some() {
            *resume_handle = None;
            res = connect_live(lv, system, temp, actions_on, None).await;
        }

        match res {
            Ok((handle, mut ev_rx)) => {
                // Re-sync freshest frame if still recent
                for f in frames.values() {
                    if f.at.elapsed().as_secs_f64() <= FRAME_MAX_AGE_SECS {
                        let _ = handle.send_image(f.jpeg.clone()).await;
                    }
                }
                *live_handle = Some(handle);
                let tx = int_tx.clone();
                tokio::spawn(async move {
                    while let Some(ev) = ev_rx.recv().await {
                        if tx.send(InternalMsg::Live(ev)).await.is_err() {
                            break;
                        }
                    }
                });
                true
            }
            Err(err) => {
                let _ = out_tx.try_send(Message::Text(json!({"type": "error", "message": err}).to_string().into()));
                if cur_state != "idle" {
                    *cur_state = "idle".into();
                    let _ = out_tx.try_send(Message::Text(json!({"type": "state", "value": "idle"}).to_string().into()));
                }
                false
            }
        }
    }

    loop {
        tokio::select! {
            Ok(_) = reset_rx.recv() => {
                if let Some(h) = live_handle.take() {
                    h.close().await;
                }
                resume_handle = None;
                go_away_pending = false;
                turn_open = false;
                in_buf.clear();
                out_buf.clear();
                pcm_buf.clear();
            }
            Some(internal) = int_rx.recv() => {
                match internal {
                    InternalMsg::PttState(down) => {
                        send_json(&out_tx, json!({"type": "ptt_state", "down": down}));
                    }
                    InternalMsg::TimerDone { label, secs } => {
                        let msg = if label.is_empty() {
                            format!("(Acaba de sonar el temporizador de {}. Avisa al usuario con naturalidad.)", actions::fmt_duration(secs))
                        } else {
                            format!("(Acaba de sonar el temporizador «{label}» de {}. Avisa al usuario con naturalidad.)", actions::fmt_duration(secs))
                        };
                        live_user = false;
                        if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                            if let Some(h) = &live_handle {
                                let _ = h.send_text(msg, vec![]).await;
                            }
                        }
                    }
                    InternalMsg::Live(ev) => match ev {
                        LiveEvent::SessionResume(h) => {
                            resume_handle = Some(h);
                        }
                        LiveEvent::GoAway => {
                            if !turn_open {
                                if let Some(h) = live_handle.take() {
                                    h.close().await;
                                }
                            } else {
                                go_away_pending = true;
                            }
                        }
                        LiveEvent::InText(chunk) => {
                            live_user = true;
                            in_buf.push_str(&chunk);
                            let said = in_buf.trim().to_string();
                            if !said.is_empty() {
                                send_json(&out_tx, json!({"type": "user_text", "text": said}));
                                if live_gesture.is_none() {
                                    live_gesture = play::guess(&said).map(|s| s.to_string());
                                }
                            }
                            if !turn_open {
                                set_state(&mut cur_state, "listening", &out_tx);
                            }
                        }
                        LiveEvent::Audio(pcm) => {
                            if !turn_open {
                                turn_open = true;
                                sentence_id += 1;
                                out_buf.clear();
                                client_playing = true;
                                let gestures: Vec<String> = live_gesture.take().into_iter().collect();
                                set_state(&mut cur_state, "speaking", &out_tx);
                                send_json(&out_tx, json!({
                                    "type": "sentence",
                                    "id": sentence_id,
                                    "text": "",
                                    "emotion": emotion,
                                    "gestures": gestures,
                                }));
                            }
                            let _ = out_tx.send(Message::Binary(pcm.into())).await;
                        }
                        LiveEvent::OutText(chunk) => {
                            if !turn_open {
                                turn_open = true;
                                sentence_id += 1;
                                out_buf.clear();
                                client_playing = true;
                                let gestures: Vec<String> = live_gesture.take().into_iter().collect();
                                set_state(&mut cur_state, "speaking", &out_tx);
                                send_json(&out_tx, json!({
                                    "type": "sentence",
                                    "id": sentence_id,
                                    "text": "",
                                    "emotion": emotion,
                                    "gestures": gestures,
                                }));
                            }
                            out_buf.push_str(&chunk);
                            let clean = clean_spoken_text(&out_buf);
                            if live_emo.is_empty() && clean.len() >= 12 {
                                live_emo = "guess".into();
                                if let Some(g) = guess_emotion(&clean) {
                                    emotion = g.to_string();
                                    send_json(&out_tx, json!({"type": "express", "emotion": g, "gestures": []}));
                                }
                            }
                            send_json(&out_tx, json!({"type": "caption_delta", "id": sentence_id, "text": clean}));
                        }
                        LiveEvent::ToolCall(calls) => {
                            let mut responses = Vec::new();
                            let mut to_exec: Vec<PreparedAction> = Vec::new();
                            let act_cfg = actions::get_config(&state.config);
                            let is_mixed = live_mixed_at.map(|t| t.elapsed().as_secs_f64() < 15.0).unwrap_or(false);

                            for fc in calls {
                                if fc.name == "expresar" {
                                    let emo = fc.args.get("emocion").and_then(|v| v.as_str()).unwrap_or("");
                                    let ges = fc.args.get("gesto").and_then(|v| v.as_str()).unwrap_or("");
                                    let valid_emo = if EMOTIONS.contains(&emo) { Some(emo) } else { None };
                                    let valid_ges = if GESTURES.contains(&ges) { Some(ges) } else { None };
                                    if let Some(e) = valid_emo {
                                        emotion = e.to_string();
                                        live_emo = "tool".into();
                                    }
                                    if valid_emo.is_some() || valid_ges.is_some() {
                                        let g_arr: Vec<&str> = valid_ges.into_iter().collect();
                                        send_json(&out_tx, json!({
                                            "type": "express",
                                            "emotion": valid_emo,
                                            "gestures": g_arr,
                                        }));
                                    }
                                    responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": true}}));
                                } else if fc.name == "recordar" {
                                    if !is_mixed {
                                        if let Some(fact) = fc.args.get("dato").and_then(|v| v.as_str()) {
                                            state.store.add_memory(fact);
                                        }
                                    }
                                    responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": true}}));
                                } else if fc.name == "ejecutar_accion" {
                                    if !live_user {
                                        responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": false, "error": "solo cuando el usuario lo pide"}}));
                                    } else if !act_cfg.enabled {
                                        responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": false, "error": "acciones desactivadas"}}));
                                    } else {
                                        let accion = fc.args.get("accion").and_then(|v| v.as_str()).unwrap_or("");
                                        let arg1 = fc.args.get("arg1").and_then(|v| v.as_str()).unwrap_or("");
                                        let arg2 = fc.args.get("arg2").and_then(|v| v.as_str()).unwrap_or("");
                                        match actions::prepare(accion, arg1, arg2) {
                                            Ok(prep) => {
                                                to_exec.push(prep);
                                                responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": true, "status": "en_marcha"}}));
                                            }
                                            Err(err) => {
                                                responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": false, "error": err}}));
                                            }
                                        }
                                    }
                                } else {
                                    responses.push(json!({"id": fc.id, "name": fc.name, "response": {"ok": false, "error": "herramienta desconocida"}}));
                                }
                            }

                            if !responses.is_empty() {
                                if let Some(h) = &live_handle {
                                    let _ = h.send_tool_response(responses).await;
                                }
                            }

                            for act in to_exec.into_iter().take(actions::MAX_PER_REPLY) {
                                let auto_ok = !is_mixed && (act_cfg.full || !act_cfg.ask || act_cfg.always.iter().any(|a| a == &act.name));
                                if auto_ok {
                                    run_prepared_action(&act, "auto", &state, &out_tx, &int_tx);
                                } else {
                                    let mut req = act.public(&state.config);
                                    if let Some(obj) = req.as_object_mut() {
                                        obj.insert("type".into(), json!("action_request"));
                                        if is_mixed {
                                            obj.insert("confirm".into(), json!(true));
                                        }
                                    }
                                    send_json(&out_tx, req);
                                    pending_actions.insert(act.id.clone(), act);
                                }
                            }
                        }
                        LiveEvent::Interrupted => {
                            live_emo.clear();
                            turn_open = false;
                            client_playing = false;
                            out_buf.clear();
                            send_json(&out_tx, json!({"type": "interrupt"}));
                            set_state(&mut cur_state, "listening", &out_tx);
                        }
                        LiveEvent::TurnComplete => {
                            let reply = clean_spoken_text(&out_buf);
                            let user_said = in_buf.trim().to_string();
                            let is_mixed = live_mixed_at.map(|t| t.elapsed().as_secs_f64() < 15.0).unwrap_or(false);
                            if !user_said.is_empty() {
                                state.store.add_message("user", &user_said, None);
                                // Check short voice approval/denial for pending action cards (disabled when screen/mixed audio active)
                                if !pending_actions.is_empty() && !is_mixed {
                                    let p = plain(&user_said);
                                    let words: Vec<&str> = p.split_whitespace().collect();
                                    if words.len() <= 3 {
                                        let verdict = if words.iter().any(|w| matches!(*w, "si" | "dale" | "adelante" | "ok" | "vale")) {
                                            Some("allow")
                                        } else if words.iter().any(|w| matches!(*w, "no" | "cancela" | "cancelar" | "para")) {
                                            Some("deny")
                                        } else {
                                            None
                                        };
                                        if let Some(v) = verdict {
                                            let items: Vec<PreparedAction> = pending_actions.drain().map(|(_, a)| a).collect();
                                            for act in items {
                                                if v == "allow" {
                                                    run_prepared_action(&act, "allow", &state, &out_tx, &int_tx);
                                                } else {
                                                    actions::log_entry(&state.config, &act.name, &act.detail, "deny", "cancelado");
                                                    send_json(&out_tx, json!({
                                                        "type": "action_done",
                                                        "id": act.id,
                                                        "action": act.name,
                                                        "ok": false,
                                                        "text": "Cancelado"
                                                    }));
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            let pers = personality::active(&state.config);
                            let base_mood = pers.get("base_mood").and_then(|v| v.as_str()).unwrap_or("neutral");
                            if !reply.is_empty() {
                                state.store.add_message("assistant", &reply, Some(&emotion));
                                let expr = pers.get("traits").and_then(|t| t.get("expressiveness")).and_then(|v| v.as_f64()).unwrap_or(0.6);
                                state.mood.feel(&emotion, base_mood, expr);
                            }
                            if turn_open {
                                let mood_emo = state
                                    .mood
                                    .public(base_mood)
                                    .get("emotion")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("neutral")
                                    .to_string();
                                send_json(&out_tx, json!({"type": "sentence_end", "id": sentence_id}));
                                send_json(&out_tx, json!({"type": "reply_end", "text": reply, "mood": mood_emo}));
                                turn_open = false;
                            }
                            if go_away_pending {
                                go_away_pending = false;
                                if let Some(h) = live_handle.take() {
                                    h.close().await;
                                }
                            }
                            live_user = false;
                            live_emo.clear();
                            in_buf.clear();
                            out_buf.clear();
                            if !client_playing {
                                set_state(&mut cur_state, "idle", &out_tx);
                            }
                        }
                        LiveEvent::Closed(reason) => {
                            live_handle = None;
                            go_away_pending = false;
                            turn_open = false;
                            let note = match reason {
                                Some(r) => format!("Conexión en vivo cerrada ({r}); se reconectará en el siguiente turno."),
                                None => "La conexión en vivo se cerró; se reconectará en el siguiente turno.".to_string(),
                            };
                            send_json(&out_tx, json!({"type": "notice", "message": note}));
                            set_state(&mut cur_state, "idle", &out_tx);
                        }
                    }
                }
            }
            incoming = ws_stream.next() => {
                let Some(Ok(msg)) = incoming else { break };
                match msg {
                    Message::Binary(bin) => {
                        let mut data = bin.to_vec();
                        if data.len() % 2 == 1 { data.pop(); }
                        if client_playing && !state.config.barge_in {
                            pcm_buf.clear();
                            continue;
                        }
                        pcm_buf.extend_from_slice(&data);
                        if pcm_buf.len() < 3072 {
                            continue;
                        }
                        let chunk = std::mem::take(&mut pcm_buf);
                        if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                            if let Some(h) = &live_handle {
                                let _ = h.send_audio(chunk).await;
                            }
                        }
                    }
                    Message::Text(txt) => {
                        let Ok(data) = serde_json::from_str::<Value>(&txt) else { continue };
                        let kind = data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                        match kind {
                            "text" => {
                                let text: String = data.get("text").and_then(|v| v.as_str()).unwrap_or("").trim().chars().take(2000).collect();
                                if text.is_empty() { continue; }
                                live_user = true;
                                in_buf = text.clone();
                                live_gesture = play::guess(&text).map(|s| s.to_string());
                                send_json(&out_tx, json!({"type": "user_text", "text": text}));
                                set_state(&mut cur_state, "thinking", &out_tx);
                                let mut prompt_to_send = text.clone();
                                if game_mode.as_deref() == Some("rps") {
                                    let p = plain(&text);
                                    if p.contains("piedra") || p.contains("papel") || p.contains("tijera") {
                                        let choice = pick_rps_choice();
                                        send_json(&out_tx, json!({"type": "rps", "choice": choice}));
                                        prompt_to_send = format!("{text}\n(En esta ronda de piedra, papel o tijera tú elegiste «{choice}». Reacciona con espontaneidad al resultado.)");
                                    }
                                }
                                if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                                    let fresh: Vec<String> = frames
                                        .values()
                                        .filter(|f| f.at.elapsed().as_secs_f64() <= FRAME_MAX_AGE_SECS)
                                        .map(|f| f.jpeg.clone())
                                        .collect();
                                    if let Some(h) = &live_handle {
                                        let _ = h.send_text(prompt_to_send, fresh).await;
                                    }
                                }
                            }
                            "start" => {
                                live_user = false;
                                set_state(&mut cur_state, "thinking", &out_tx);
                                if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                                    if let Some(h) = &live_handle {
                                        let _ = h.send_text(GREETING.to_string(), vec![]).await;
                                    }
                                }
                            }
                            "touch" | "look" => {
                                let zone = data.get("zone").or_else(|| data.get("kind")).and_then(|v| v.as_str()).unwrap_or("");
                                if !zone.is_empty() && !turn_open {
                                    live_user = false;
                                    let note = if kind == "touch" {
                                        format!("(El usuario te acaba de dar un toque cariñoso en: {zone}. Reacciona de forma breve y natural.)")
                                    } else {
                                        format!("(El usuario te está mirando de cerca: {zone}. Reacciona de forma breve.)")
                                    };
                                    if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                                        if let Some(h) = &live_handle {
                                            let _ = h.send_text(note, vec![]).await;
                                        }
                                    }
                                }
                            }
                            "game" => {
                                let mode = data.get("mode").and_then(|v| v.as_str()).unwrap_or("").trim();
                                if mode.is_empty() || mode == "stop" {
                                    game_mode = None;
                                    continue;
                                }
                                game_mode = Some(mode.to_string());
                                live_user = false;
                                let game_prompt = match mode {
                                    "rps" => {
                                        let choice = pick_rps_choice();
                                        send_json(&out_tx, json!({"type": "rps", "choice": choice}));
                                        format!("(El usuario inició Piedra, Papel o Tijera contigo. Cuenta «¡Piedra, papel o tijera!» con emoción y revela que sacaste «{choice}», preguntándole qué sacó.)")
                                    }
                                    "trivia" => "(El usuario inició una ronda de Trivia contigo. Hazle una pregunta curiosa y divertida con 3 opciones breves y espera su respuesta.)".to_string(),
                                    "twenty" => "(El usuario inició el juego de las 20 preguntas. Piensa en un objeto, animal o personaje conocido en secreto y dile que ya lo tienes pensado para que empiece a hacerte preguntas de sí o no.)".to_string(),
                                    "ispy" => "(El usuario inició «Veo, veo» contigo. Si tienes imagen de cámara o pantalla activa, elige algo visible; si no, imagina algo típico de un escritorio y di «¡Veo, veo! ¿Qué ves?» dando una pista del color o inicial.)".to_string(),
                                    _ => continue,
                                };
                                set_state(&mut cur_state, "thinking", &out_tx);
                                if ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                                    let fresh: Vec<String> = frames
                                        .values()
                                        .filter(|f| f.at.elapsed().as_secs_f64() <= FRAME_MAX_AGE_SECS)
                                        .map(|f| f.jpeg.clone())
                                        .collect();
                                    if let Some(h) = &live_handle {
                                        let _ = h.send_text(game_prompt, fresh).await;
                                    }
                                }
                            }
                            "ptt_config" => {
                                if let Some(t) = ptt_task.take() {
                                    t.abort();
                                }
                                let enabled = data.get("enabled").and_then(|v| v.as_bool()).unwrap_or(false);
                                #[cfg(windows)]
                                if enabled {
                                    let key_name = data.get("key").and_then(|v| v.as_str()).unwrap_or("AltRight");
                                    let vk = ptt_vk(key_name);
                                    let tx = int_tx.clone();
                                    ptt_task = Some(tokio::spawn(async move {
                                        use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
                                        let mut was_down = false;
                                        loop {
                                            tokio::time::sleep(std::time::Duration::from_millis(35)).await;
                                            let down = unsafe { (GetAsyncKeyState(vk) as u16 & 0x8000) != 0 };
                                            if down != was_down {
                                                was_down = down;
                                                if tx.send(InternalMsg::PttState(down)).await.is_err() {
                                                    break;
                                                }
                                            }
                                        }
                                    }));
                                }
                                #[cfg(not(windows))]
                                let _ = enabled;
                            }
                            "interrupt" => {
                                turn_open = false;
                                client_playing = false;
                                out_buf.clear();
                                send_json(&out_tx, json!({"type": "interrupt"}));
                                set_state(&mut cur_state, "idle", &out_tx);
                            }
                            "frame" => {
                                let src = data.get("source").and_then(|v| v.as_str()).unwrap_or("");
                                let jpeg = data.get("jpeg").and_then(|v| v.as_str()).unwrap_or("");
                                if (src == "camera" || src == "screen") && jpeg.starts_with("/9j/") && jpeg.len() <= 2_500_000 {
                                    if src == "screen" {
                                        live_mixed_at = Some(Instant::now());
                                    }
                                    frames.insert(src.to_string(), FrameEntry { jpeg: jpeg.to_string(), at: Instant::now() });
                                    if live_handle.is_some() && last_frame_sent.elapsed().as_secs_f64() >= 1.0 {
                                        last_frame_sent = Instant::now();
                                        if let Some(h) = &live_handle {
                                            let _ = h.send_image(jpeg.to_string()).await;
                                        }
                                    }
                                }
                            }
                            "frame_stop" => {
                                if let Some(src) = data.get("source").and_then(|v| v.as_str()) {
                                    frames.remove(src);
                                }
                            }
                            "screen_audio" => {
                                if !frames.contains_key("screen") || client_playing {
                                    continue;
                                }
                                live_mixed_at = Some(Instant::now());
                                if let Some(b64) = data.get("pcm").and_then(|v| v.as_str()) {
                                    if let Ok(mut raw) = B64.decode(b64) {
                                        if raw.len() % 2 == 1 { raw.pop(); }
                                        if !raw.is_empty() && ensure_live(&mut live_handle, &state, &int_tx, &out_tx, &mut cur_state, &mut resume_handle, &frames).await {
                                            if let Some(h) = &live_handle {
                                                for chunk in raw.chunks(3200) {
                                                    let _ = h.send_audio(chunk.to_vec()).await;
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            "action_answer" => {
                                let id = data.get("id").and_then(|v| v.as_str()).unwrap_or("");
                                let answer = data.get("answer").and_then(|v| v.as_str()).unwrap_or("");
                                if let Some(act) = pending_actions.remove(id) {
                                    match answer {
                                        "allow" | "always" => {
                                            if answer == "always" {
                                                actions::save_config(&state.config, None, None, None, Some(&act.name), None);
                                            }
                                            run_prepared_action(&act, answer, &state, &out_tx, &int_tx);
                                        }
                                        _ => {
                                            actions::log_entry(&state.config, &act.name, &act.detail, "deny", "cancelado");
                                            send_json(&out_tx, json!({
                                                "type": "action_done",
                                                "id": act.id,
                                                "action": act.name,
                                                "ok": false,
                                                "text": "Cancelado"
                                            }));
                                        }
                                    }
                                }
                            }
                            "playback_end" => {
                                client_playing = false;
                                if !turn_open {
                                    set_state(&mut cur_state, "idle", &out_tx);
                                }
                            }
                            _ => {}
                        }
                    }
                    Message::Close(_) => break,
                    _ => {}
                }
            }
        }
    }

    if let Some(t) = ptt_task.take() {
        t.abort();
    }
    if let Some(h) = live_handle {
        h.close().await;
    }
    writer.abort();
}

fn run_prepared_action(
    act: &PreparedAction,
    decision: &str,
    state: &Arc<AppState>,
    out_tx: &mpsc::Sender<Message>,
    int_tx: &mpsc::Sender<InternalMsg>,
) {
    if let Some(secs) = act.timer_secs {
        let label = act.arg2.clone();
        let tx = int_tx.clone();
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_secs(secs)).await;
            let _ = tx.send(InternalMsg::TimerDone { label, secs }).await;
        });
    }
    match actions::execute(act) {
        Ok(res) => {
            actions::log_entry(&state.config, &act.name, &act.detail, decision, &res);
            let _ = out_tx.try_send(Message::Text(
                json!({
                    "type": "action_done",
                    "id": act.id,
                    "action": act.name,
                    "ok": true,
                    "text": res
                })
                .to_string()
                .into(),
            ));
        }
        Err(err) => {
            actions::log_entry(&state.config, &act.name, &act.detail, decision, &err);
            let _ = out_tx.try_send(Message::Text(
                json!({
                    "type": "action_done",
                    "id": act.id,
                    "action": act.name,
                    "ok": false,
                    "text": err
                })
                .to_string()
                .into(),
            ));
        }
    }
}
