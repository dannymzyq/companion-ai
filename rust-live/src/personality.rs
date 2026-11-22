use crate::config::AppConfig;
use crate::prompt::EMOTIONS;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::fs;
use std::sync::OnceLock;
use uuid::Uuid;

pub const DEFAULT_ID: &str = "confianza";
pub const MAX_CUSTOM: usize = 30;

pub fn traits_meta() -> Value {
    json!({
        "warmth":         {"label": "Calidez", "low": "Poca", "high": "Mucha", "default": 0.7},
        "playfulness":    {"label": "Humor", "low": "Nada", "high": "Mucho", "default": 0.5},
        "sarcasm":        {"label": "Ironía", "low": "Nada", "high": "Mucha", "default": 0.2},
        "shyness":        {"label": "Timidez", "low": "Nada", "high": "Mucha", "default": 0.2},
        "curiosity":      {"label": "Curiosidad", "low": "Poca", "high": "Pregunta por todo", "default": 0.6},
        "energy":         {"label": "Energía", "low": "Calma", "high": "A tope", "default": 0.5},
        "expressiveness": {"label": "Expresividad", "low": "Lo guarda", "high": "Lo muestra todo", "default": 0.6},
        "assertiveness":  {"label": "Opiniones propias", "low": "Te da la razón", "high": "Discute y opina", "default": 0.5},
        "talkativeness":  {"label": "Cuánto habla", "low": "Lo justo", "high": "Se explaya", "default": 0.4},
    })
}

pub fn formality_meta() -> Value {
    json!({"casual": "Casual", "neutral": "Neutro", "formal": "Formal"})
}

fn junk_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[\x00-\x08\x0b-\x1f\x7f\[\]{}<>]+").unwrap())
}

fn spaces_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[ \t]+").unwrap())
}

fn clean_text(val: Option<&Value>, limit: usize, lines: bool) -> String {
    let raw = val.and_then(|v| v.as_str()).unwrap_or("");
    let replaced = if lines {
        raw.replace('\r', "")
    } else {
        raw.replace('\n', " ")
    };
    let s = junk_re().replace_all(&replaced, " ");
    let s = spaces_re().replace_all(&s, " ");
    s.trim().chars().take(limit).collect()
}

fn clean_items(val: Option<&Value>, max_n: usize, limit: usize, split_newlines_only: bool) -> Vec<String> {
    let mut raw_list: Vec<String> = Vec::new();
    match val {
        Some(Value::String(s)) => {
            if split_newlines_only {
                raw_list.extend(s.split('\n').map(|x| x.to_string()));
            } else {
                raw_list.extend(s.split(|c| c == ',' || c == ';' || c == '\n').map(|x| x.to_string()));
            }
        }
        Some(Value::Array(arr)) => {
            for v in arr {
                if let Some(s) = v.as_str() {
                    raw_list.push(s.to_string());
                }
            }
        }
        _ => {}
    }
    let mut out = Vec::new();
    for item in raw_list {
        let t = clean_text(Some(&Value::String(item)), limit, false);
        if !t.is_empty() && !out.iter().any(|x: &String| x.eq_ignore_ascii_case(&t)) {
            out.push(t);
            if out.len() >= max_n {
                break;
            }
        }
    }
    out
}

pub fn clean_personality(raw: &Value, partial: bool) -> Result<Map<String, Value>, String> {
    let name = clean_text(raw.get("name"), 40, false);
    if name.is_empty() && !partial {
        return Err("Ponle un nombre a la personalidad.".into());
    }
    let traits_in = raw.get("traits").and_then(|v| v.as_object());
    let defaults = [
        ("warmth", 0.7),
        ("playfulness", 0.5),
        ("sarcasm", 0.2),
        ("shyness", 0.2),
        ("curiosity", 0.6),
        ("energy", 0.5),
        ("expressiveness", 0.6),
        ("assertiveness", 0.5),
        ("talkativeness", 0.4),
    ];
    let mut traits = Map::new();
    for (k, def) in defaults {
        let val = traits_in
            .and_then(|o| o.get(k))
            .and_then(|v| v.as_f64())
            .unwrap_or(def)
            .clamp(0.0, 1.0);
        traits.insert(k.to_string(), json!((val * 100.0).round() / 100.0));
    }
    let mood = raw
        .get("base_mood")
        .and_then(|v| v.as_str())
        .filter(|m| EMOTIONS.contains(m))
        .unwrap_or("neutral");
    let formality = raw
        .get("formality")
        .and_then(|v| v.as_str())
        .filter(|f| matches!(*f, "casual" | "neutral" | "formal"))
        .unwrap_or("casual");

    let emotions: Vec<String> = clean_items(raw.get("emotions"), 4, 20, false)
        .into_iter()
        .filter(|e| EMOTIONS.contains(&e.as_str()))
        .take(3)
        .collect();

    let mut out = Map::new();
    out.insert("name".into(), json!(name));
    out.insert("summary".into(), json!(clean_text(raw.get("summary"), 120, false)));
    out.insert("description".into(), json!(clean_text(raw.get("description"), 700, true)));
    out.insert("traits".into(), Value::Object(traits));
    out.insert("formality".into(), json!(formality));
    out.insert("speech".into(), json!(clean_text(raw.get("speech"), 400, true)));
    out.insert("catchphrases".into(), json!(clean_items(raw.get("catchphrases"), 4, 40, false)));
    out.insert("likes".into(), json!(clean_items(raw.get("likes"), 8, 60, false)));
    out.insert("dislikes".into(), json!(clean_items(raw.get("dislikes"), 6, 60, false)));
    out.insert("base_mood".into(), json!(mood));
    out.insert("emotions".into(), json!(emotions));
    out.insert("examples".into(), json!(clean_items(raw.get("examples"), 5, 200, true)));
    out.insert("opinions".into(), json!(clean_items(raw.get("opinions"), 5, 160, true)));
    out.insert("reactions".into(), json!(clean_items(raw.get("reactions"), 4, 160, true)));
    Ok(out)
}

pub fn catalog(cfg: &AppConfig) -> Vec<Value> {
    let path = cfg.personas_dir.join("personalidades.json");
    let raw: Vec<Value> = fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default();
    let mut out = Vec::new();
    for p in raw {
        let Some(id) = p.get("id").and_then(|v| v.as_str()) else {
            continue;
        };
        if let Ok(mut cleaned) = clean_personality(&p, true) {
            cleaned.insert("id".into(), json!(id));
            cleaned.insert("builtin".into(), json!(true));
            out.push(Value::Object(cleaned));
        }
    }
    if out.is_empty() {
        out.push(json!({
            "id": DEFAULT_ID,
            "name": "En confianza",
            "summary": "Cercana, natural y expresiva.",
            "description": "Cercana, con sentido del humor y trato natural.",
            "traits": {"warmth": 0.8, "playfulness": 0.6, "sarcasm": 0.2, "shyness": 0.15, "curiosity": 0.65, "energy": 0.55, "expressiveness": 0.7, "assertiveness": 0.5, "talkativeness": 0.45},
            "formality": "casual",
            "speech": "Natural y cercana.",
            "catchphrases": [],
            "likes": [],
            "dislikes": [],
            "base_mood": "feliz",
            "emotions": ["feliz", "emocionada", "pensativa"],
            "examples": [],
            "opinions": [],
            "reactions": [],
            "builtin": true
        }));
    }
    out
}

pub fn custom_list(cfg: &AppConfig) -> Vec<Value> {
    let s = cfg.load_settings();
    let arr = s
        .get("personality")
        .and_then(|p| p.get("custom"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut out = Vec::new();
    for item in arr {
        let Some(id) = item.get("id").and_then(|v| v.as_str()) else {
            continue;
        };
        if !id.starts_with("c_") {
            continue;
        }
        if let Ok(mut cleaned) = clean_personality(&item, true) {
            cleaned.insert("id".into(), json!(id));
            cleaned.insert("builtin".into(), json!(false));
            cleaned.insert(
                "from".into(),
                json!(item.get("from").and_then(|v| v.as_str()).unwrap_or("")),
            );
            out.push(Value::Object(cleaned));
        }
    }
    out
}

pub fn all(cfg: &AppConfig) -> Vec<Value> {
    let mut list = catalog(cfg);
    list.extend(custom_list(cfg));
    list
}

pub fn find(cfg: &AppConfig, pid: &str) -> Option<Value> {
    all(cfg)
        .into_iter()
        .find(|p| p.get("id").and_then(|v| v.as_str()) == Some(pid))
}

pub fn active_id(cfg: &AppConfig) -> String {
    let s = cfg.load_settings();
    let pid = s
        .get("personality")
        .and_then(|p| p.get("active"))
        .and_then(|v| v.as_str())
        .unwrap_or(DEFAULT_ID);
    if find(cfg, pid).is_some() {
        pid.to_string()
    } else {
        DEFAULT_ID.to_string()
    }
}

pub fn active(cfg: &AppConfig) -> Value {
    let id = active_id(cfg);
    find(cfg, &id).unwrap_or_else(|| catalog(cfg).remove(0))
}

pub fn select(cfg: &AppConfig, pid: &str) -> Result<(), String> {
    if find(cfg, pid).is_none() {
        return Err("Esa personalidad no existe.".into());
    }
    cfg.update_settings(|obj| {
        let mut p = obj
            .get("personality")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        p.insert("active".into(), json!(pid));
        obj.insert("personality".into(), Value::Object(p));
    });
    Ok(())
}

pub fn save_custom(cfg: &AppConfig, raw: &Value) -> Result<Value, String> {
    let data = clean_personality(raw, false)?;
    let existing = custom_list(cfg);
    let mut items: Vec<Value> = existing;
    let req_id = raw.get("id").and_then(|v| v.as_str()).unwrap_or("");
    let final_id: String;

    if req_id.starts_with("c_")
        && items
            .iter()
            .any(|c| c.get("id").and_then(|v| v.as_str()) == Some(req_id))
    {
        final_id = req_id.to_string();
        for item in &mut items {
            if item.get("id").and_then(|v| v.as_str()) == Some(req_id) {
                let from_val = item
                    .get("from")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let mut m = data.clone();
                m.insert("id".into(), json!(final_id));
                m.insert("from".into(), json!(from_val));
                *item = Value::Object(m);
            }
        }
    } else {
        if items.len() >= MAX_CUSTOM {
            return Err(format!(
                "Ya tienes {MAX_CUSTOM} personalidades propias: borra alguna antes."
            ));
        }
        let from_req = raw
            .get("from")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(req_id);
        let from_ok = if find(cfg, from_req).is_some() {
            from_req.to_string()
        } else {
            String::new()
        };
        final_id = format!("c_{}", &Uuid::new_v4().simple().to_string()[..8]);
        let mut m = data;
        m.insert("id".into(), json!(final_id));
        m.insert("from".into(), json!(from_ok));
        items.push(Value::Object(m));
    }

    cfg.update_settings(|obj| {
        let mut p = obj
            .get("personality")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        p.insert("custom".into(), Value::Array(items));
        p.insert("active".into(), json!(final_id));
        obj.insert("personality".into(), Value::Object(p));
    });

    Ok(find(cfg, &final_id).unwrap_or_else(|| active(cfg)))
}

pub fn delete_custom(cfg: &AppConfig, pid: &str) {
    let existing = custom_list(cfg);
    let gone_from = existing
        .iter()
        .find(|c| c.get("id").and_then(|v| v.as_str()) == Some(pid))
        .and_then(|c| c.get("from"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let kept: Vec<Value> = existing
        .into_iter()
        .filter(|c| c.get("id").and_then(|v| v.as_str()) != Some(pid))
        .collect();
    let cur_active = active_id(cfg);
    let next_active = if cur_active == pid {
        if catalog(cfg)
            .iter()
            .any(|p| p.get("id").and_then(|v| v.as_str()) == Some(gone_from.as_str()))
        {
            gone_from
        } else {
            DEFAULT_ID.to_string()
        }
    } else {
        cur_active
    };

    cfg.update_settings(|obj| {
        let mut p = obj
            .get("personality")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        p.insert("custom".into(), Value::Array(kept));
        p.insert("active".into(), json!(next_active));
        obj.insert("personality".into(), Value::Object(p));
    });
}

pub fn temper(p: &Value) -> Value {
    let t = p.get("traits").and_then(|v| v.as_object());
    let get = |k: &str, d: f64| t.and_then(|o| o.get(k)).and_then(|v| v.as_f64()).unwrap_or(d);
    let shy = get("shyness", 0.2);
    let warm = get("warmth", 0.7);
    let sharp = get("sarcasm", 0.2).max(get("assertiveness", 0.5) * 0.8);
    json!({
        "shy": (shy * 100.0).round() / 100.0,
        "warm": (warm * 100.0).round() / 100.0,
        "sharp": (sharp * 100.0).round() / 100.0,
    })
}

pub fn public(cfg: &AppConfig) -> Value {
    json!({
        "active": active_id(cfg),
        "personalities": all(cfg),
        "default": DEFAULT_ID,
        "traits": traits_meta(),
        "formality": formality_meta(),
        "emotions": EMOTIONS,
        "max_custom": MAX_CUSTOM,
    })
}
