use chrono::{Local, TimeZone};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredMessage {
    pub role: String,
    pub text: String,
    pub emotion: Option<String>,
    pub ts: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredMemory {
    pub fact: String,
    pub ts: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredSummary {
    pub text: String,
    pub ts: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct StoreData {
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
        let data = fs::read_to_string(&file)
            .ok()
            .and_then(|s| serde_json::from_str::<StoreData>(&s).ok())
            .unwrap_or_default();
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
        // Keep last 400 messages to keep file tiny & fast
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

    pub fn add_memory(&self, fact: &str) {
        let fact = fact.trim().trim_end_matches('.').trim();
        if fact.is_empty() {
            return;
        }
        let low = fact.to_lowercase();
        let mut d = self.data.lock().unwrap();
        if d.memories
            .iter()
            .any(|m| m.fact.trim_end_matches('.').to_lowercase() == low)
        {
            return;
        }
        d.memories.push(StoredMemory {
            fact: fact.to_string(),
            ts: now_secs(),
        });
        if d.memories.len() > 200 {
            let drain = d.memories.len() - 200;
            d.memories.drain(0..drain);
        }
        self.save(&d);
    }

    pub fn memories(&self, limit: usize) -> Vec<String> {
        let d = self.data.lock().unwrap();
        let start = d.memories.len().saturating_sub(limit);
        d.memories[start..].iter().map(|m| m.fact.clone()).collect()
    }

    pub fn delete_memory(&self, fact: &str) {
        let mut d = self.data.lock().unwrap();
        d.memories.retain(|m| m.fact != fact);
        self.save(&d);
    }

    pub fn public_memory(&self) -> Value {
        let d = self.data.lock().unwrap();
        let facts: Vec<String> = d.memories.iter().map(|m| m.fact.clone()).collect();
        let summaries: Vec<Value> = d
            .summaries
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
            .collect();
        json!({ "facts": facts, "summaries": summaries })
    }

    pub fn forget_all(&self) {
        let mut d = self.data.lock().unwrap();
        *d = StoreData::default();
        let _ = fs::remove_file(&self.file);
    }
}
