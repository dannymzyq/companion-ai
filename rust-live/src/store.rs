use crate::play::plain;
use chrono::{Local, TimeZone};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

pub fn is_private_fact(text: &str) -> bool {
    static PRIV_RE: OnceLock<Regex> = OnceLock::new();
    let re = PRIV_RE.get_or_init(|| {
        Regex::new(
            r"(?i)(\b(contrase[nñ]a|password|passwd|clave\s+secreta|api[\s_-]?key|token|seed\s*phrase|cvv|pin\s+bancario|iban)\b|\b(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{25,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b|\b(?:\d[ -]*?){13,19}\b)",
        )
        .unwrap()
    });
    re.is_match(text)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredMessage {
    pub role: String,
    pub text: String,
    pub emotion: Option<String>,
    pub ts: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredMemory {
    #[serde(default)]
    pub id: u64,
    pub fact: String,
    pub ts: f64,
    #[serde(default)]
    pub pinned: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredSummary {
    pub text: String,
    pub ts: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct StoreData {
    #[serde(default)]
    next_id: u64,
    messages: Vec<StoredMessage>,
    memories: Vec<StoredMemory>,
    summaries: Vec<StoredSummary>,
}

pub struct MemoryStore {
    file: PathBuf,
    data: Mutex<StoreData>,
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

impl MemoryStore {
    pub fn new(data_dir: &Path) -> Self {
        let file = data_dir.join("live_memory.json");
        let mut data = fs::read_to_string(&file)
            .ok()
            .and_then(|s| serde_json::from_str::<StoreData>(&s).ok())
            .unwrap_or_default();
        let mut max_id = data.next_id;
        for m in &mut data.memories {
            if m.id == 0 {
                max_id += 1;
                m.id = max_id;
            } else if m.id > max_id {
                max_id = m.id;
            }
        }
        data.next_id = max_id;
        Self {
            file,
            data: Mutex::new(data),
        }
    }

    fn save(&self, data: &StoreData) {
        let tmp = self.file.with_extension("tmp");
        if let Ok(s) = serde_json::to_string_pretty(data) {
            if fs::write(&tmp, s).is_ok() {
                let _ = fs::rename(&tmp, &self.file);
            }
        }
    }

    pub fn add_message(&self, role: &str, text: &str, emotion: Option<&str>) {
        let text = text.trim();
        if text.is_empty() {
            return;
        }
        let mut d = self.data.lock().unwrap();
        d.messages.push(StoredMessage {
            role: role.to_string(),
            text: text.to_string(),
            emotion: emotion.map(|e| e.to_string()),
            ts: now_secs(),
        });
        if d.messages.len() > 400 {
            let drain = d.messages.len() - 400;
            d.messages.drain(0..drain);
        }
        self.save(&d);
    }

    pub fn recent_messages(&self, limit: usize) -> Vec<StoredMessage> {
        let d = self.data.lock().unwrap();
        let start = d.messages.len().saturating_sub(limit);
        d.messages[start..].to_vec()
    }

    pub fn previous_ts(&self) -> Option<f64> {
        let d = self.data.lock().unwrap();
        d.messages.last().map(|m| m.ts)
    }

    pub fn add_memory(&self, fact: &str) -> bool {
        let fact = fact.trim().trim_end_matches('.').trim();
        if fact.is_empty() || is_private_fact(fact) {
            return false;
        }
        let low = fact.to_lowercase();
        let mut d = self.data.lock().unwrap();
        if d.memories
            .iter()
            .any(|m| m.fact.trim_end_matches('.').to_lowercase() == low)
        {
            return false;
        }
        d.next_id += 1;
        let id = d.next_id;
        d.memories.push(StoredMemory {
            id,
            fact: fact.to_string(),
            ts: now_secs(),
            pinned: false,
        });
        if d.memories.len() > 200 {
            // Preserve pinned memories when trimming oldest
            if let Some(pos) = d.memories.iter().position(|m| !m.pinned) {
                d.memories.remove(pos);
            }
        }
        self.save(&d);
        true
    }

    pub fn update_memory(&self, id: u64, content: Option<&str>, pinned: Option<bool>) -> bool {
        let mut d = self.data.lock().unwrap();
        let Some(item) = d.memories.iter_mut().find(|m| m.id == id) else {
            return false;
        };
        if let Some(c) = content {
            let clean = c.trim().trim_end_matches('.').trim();
            if clean.is_empty() || is_private_fact(clean) {
                return false;
            }
            item.fact = clean.to_string();
        }
        if let Some(p) = pinned {
            item.pinned = p;
        }
        self.save(&d);
        true
    }

    pub fn memories(&self, limit: usize) -> Vec<String> {
        let d = self.data.lock().unwrap();
        let mut pinned: Vec<String> = d.memories.iter().filter(|m| m.pinned).map(|m| m.fact.clone()).collect();
        let rest_cap = limit.saturating_sub(pinned.len());
        let unpinned: Vec<&StoredMemory> = d.memories.iter().filter(|m| !m.pinned).collect();
        let start = unpinned.len().saturating_sub(rest_cap);
        pinned.extend(unpinned[start..].iter().map(|m| m.fact.clone()));
        pinned
    }

    pub fn delete_memory(&self, fact: &str) {
        let mut d = self.data.lock().unwrap();
        d.memories.retain(|m| m.fact != fact);
        self.save(&d);
    }

    pub fn public_memory(&self) -> Value {
        let d = self.data.lock().unwrap();
        let facts: Vec<String> = d.memories.iter().map(|m| m.fact.clone()).collect();
        let summaries = Self::format_summaries(&d.summaries);
        json!({ "facts": facts, "summaries": summaries, "can_undo": false })
    }

    pub fn diary(&self, query: &str) -> Value {
        let q = plain(query);
        let d = self.data.lock().unwrap();
        let mut items: Vec<Value> = d
            .memories
            .iter()
            .filter(|m| q.is_empty() || plain(&m.fact).contains(&q))
            .map(|m| {
                json!({
                    "id": m.id,
                    "content": m.fact,
                    "pinned": m.pinned,
                    "ts": m.ts,
                })
            })
            .collect();
        items.sort_by(|a, b| {
            let pa = a.get("pinned").and_then(|v| v.as_bool()).unwrap_or(false);
            let pb = b.get("pinned").and_then(|v| v.as_bool()).unwrap_or(false);
            pb.cmp(&pa)
        });
        let diary: Vec<Value> = Self::format_summaries(&d.summaries)
            .into_iter()
            .filter(|s| {
                q.is_empty()
                    || s.get("text")
                        .and_then(|v| v.as_str())
                        .map(|t| plain(t).contains(&q))
                        .unwrap_or(false)
            })
            .collect();
        json!({ "items": items, "diary": diary, "can_undo": false })
    }

    pub fn export_memories(&self) -> (Vec<Value>, Vec<Value>) {
        let d = self.data.lock().unwrap();
        let mems = d
            .memories
            .iter()
            .filter(|m| !is_private_fact(&m.fact))
            .map(|m| json!({"content": m.fact, "pinned": m.pinned, "ts": m.ts}))
            .collect();
        let sums = d
            .summaries
            .iter()
            .map(|s| json!({"text": s.text, "ts": s.ts}))
            .collect();
        (mems, sums)
    }

    pub fn import_memories(&self, memories: &[Value], merge: bool) -> usize {
        let mut d = self.data.lock().unwrap();
        if !merge {
            d.memories.clear();
        }
        let mut added = 0usize;
        for m in memories {
            let content = m
                .get("content")
                .or_else(|| m.get("fact"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .trim_end_matches('.')
                .trim();
            if content.is_empty() || is_private_fact(content) {
                continue;
            }
            let pinned = m.get("pinned").and_then(|v| v.as_bool()).unwrap_or(false);
            let low = content.to_lowercase();
            if let Some(existing) = d
                .memories
                .iter_mut()
                .find(|x| x.fact.trim_end_matches('.').to_lowercase() == low)
            {
                if pinned {
                    existing.pinned = true;
                }
                continue;
            }
            d.next_id += 1;
            let next_id = d.next_id;
            d.memories.push(StoredMemory {
                id: next_id,
                fact: content.to_string(),
                ts: m.get("ts").and_then(|v| v.as_f64()).unwrap_or_else(now_secs),
                pinned,
            });
            added += 1;
        }
        self.save(&d);
        added
    }

    fn format_summaries(summaries: &[StoredSummary]) -> Vec<Value> {
        summaries
            .iter()
            .rev()
            .take(50)
            .rev()
            .map(|s| {
                let dt = Local
                    .timestamp_opt(s.ts as i64, 0)
                    .single()
                    .map(|t| t.format("%d/%m/%Y").to_string())
                    .unwrap_or_default();
                json!({"text": s.text, "date": dt})
            })
            .collect()
    }

    pub fn forget_all(&self) {
        let mut d = self.data.lock().unwrap();
        *d = StoreData::default();
        let _ = fs::remove_file(&self.file);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filters_private_facts_and_pins() {
        let tmp = std::env::temp_dir().join(format!("companion_rust_store_{}", uuid::Uuid::new_v4()));
        let _ = fs::create_dir_all(&tmp);
        let store = MemoryStore::new(&tmp);
        assert!(!store.add_memory("Mi contraseña del banco es Secreta123"));
        assert!(!store.add_memory("Mi clave es sk-1234567890abcdefghijklmnop"));
        assert!(store.add_memory("Tiene un gato llamado Mochi"));
        let d = store.diary("");
        let id = d["items"][0]["id"].as_u64().unwrap();
        assert!(store.update_memory(id, None, Some(true)));
        assert_eq!(store.diary("")["items"][0]["pinned"], json!(true));
        let _ = fs::remove_dir_all(&tmp);
    }
}
