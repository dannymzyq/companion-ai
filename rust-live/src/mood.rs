use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const HALF_LIFE: f64 = 25.0 * 60.0;
const STRONG: f64 = 0.45;
const REMEMBER: f64 = 40.0 * 60.0;

const VA: &[(&str, f64, f64)] = &[
    ("neutral", 0.0, 0.0),
    ("feliz", 0.6, 0.35),
    ("emocionada", 0.75, 0.85),
    ("timida", 0.1, -0.2),
    ("sonrojada", 0.35, 0.3),
    ("triste", -0.65, -0.45),
    ("molesta", -0.55, 0.45),
    ("sorprendida", 0.15, 0.7),
    ("pensativa", 0.0, -0.25),
    ("carinosa", 0.7, -0.05),
    ("enamorada", 0.8, 0.3),
    ("nerviosa", -0.25, 0.6),
    ("asustada", -0.6, 0.75),
    ("confundida", -0.15, 0.15),
];

fn lookup_va(emo: &str) -> Option<(f64, f64)> {
    VA.iter().find(|(k, _, _)| *k == emo).map(|(_, v, a)| (*v, *a))
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct MoodState {
    v: Option<f64>,
    a: Option<f64>,
    t: Option<f64>,
    base: Option<String>,
    last: Option<String>,
    last_t: Option<f64>,
}

pub struct MoodEngine {
    file: PathBuf,
    state: Mutex<MoodState>,
}

impl MoodEngine {
    pub fn new(data_dir: &std::path::Path) -> Self {
        let file = data_dir.join("mood.json");
        let st = fs::read_to_string(&file)
            .ok()
            .and_then(|s| serde_json::from_str::<MoodState>(&s).ok())
            .unwrap_or_default();
        Self {
            file,
            state: Mutex::new(st),
        }
    }

    fn save(&self, st: &MoodState) {
        let tmp = self.file.with_extension("tmp");
        if let Ok(s) = serde_json::to_string(st) {
            if fs::write(&tmp, s).is_ok() {
                let _ = fs::rename(&tmp, &self.file);
            }
        }
    }

    fn now_va(st: &MoodState, base: &str, now: f64) -> (f64, f64) {
        let (bv, ba) = lookup_va(base).unwrap_or((0.0, 0.0));
        let (Some(sv), Some(sa)) = (st.v, st.a) else {
            return (bv, ba);
        };
        let dt = (now - st.t.unwrap_or(now)).max(0.0);
        let k = 0.5_f64.powf(dt / HALF_LIFE);
        (bv + (sv - bv) * k, ba + (sa - ba) * k)
    }

    pub fn feel(&self, emotion: &str, base_mood: &str, expressiveness: f64) {
        let Some((ev, ea)) = lookup_va(emotion) else {
            return;
        };
        let now = now_secs();
        let mut st = self.state.lock().unwrap();
        let (mut v, mut a) = Self::now_va(&st, base_mood, now);
        let step = 0.18 + 0.32 * expressiveness.clamp(0.0, 1.0);
        v += (ev - v) * step;
        a += (ea - a) * step;
        st.v = Some((v * 1000.0).round() / 1000.0);
        st.a = Some((a * 1000.0).round() / 1000.0);
        st.t = Some(now);
        st.base = Some(base_mood.to_string());
        let (bv, ba) = lookup_va(base_mood).unwrap_or((0.0, 0.0));
        if (ev - bv).hypot(ea - ba) >= STRONG + 0.25 * (1.0 - expressiveness) && emotion != base_mood {
            st.last = Some(emotion.to_string());
            st.last_t = Some(now);
        }
        self.save(&st);
    }

    pub fn describe_for(&self, base_mood: &str, speaks: &str) -> String {
        let masc = speaks == "m";
        let now = now_secs();
        let st = self.state.lock().unwrap();
        if st.v.is_none() {
            return String::new();
        }
        let (v, a) = Self::now_va(&st, base_mood, now);
        let last = st.last.clone();
        let last_t = st.last_t.unwrap_or(0.0);
        drop(st);

        let (bv, ba) = lookup_va(base_mood).unwrap_or((0.0, 0.0));
        let mut parts = Vec::new();
        if (v - bv).hypot(a - ba) >= 0.12 {
            let mood = if v > 0.5 {
                "de muy buen humor"
            } else if v > 0.2 {
                "de buen humor"
            } else if v < -0.4 && a < 0.0 {
                if masc { "algo decaído" } else { "algo decaída" }
            } else if v < -0.3 {
                if masc { "molesto o tenso" } else { "molesta o tensa" }
            } else if v < -0.15 {
                if masc { "un poco bajo de ánimo" } else { "un poco baja de ánimo" }
            } else {
                if masc { "tranquilo" } else { "tranquila" }
            };
            let energy = if a > 0.5 {
                " y con mucha energía"
            } else if a > 0.25 {
                " y con energía"
            } else if a < -0.25 {
                " y sin mucha energía"
            } else {
                ""
            };
            parts.push(format!("Ahora mismo estás {mood}{energy}"));
        }
        if let Some(l) = last {
            if now - last_t < REMEMBER {
                let mins = ((now - last_t) / 60.0).round().max(1.0) as u64;
                let word = match (l.as_str(), masc) {
                    ("timida", true) => "tímido",
                    ("timida", false) => "tímida",
                    ("carinosa", true) => "cariñoso",
                    ("carinosa", false) => "cariñosa",
                    ("emocionada", true) => "emocionado",
                    ("sonrojada", true) => "sonrojado",
                    ("molesta", true) => "molesto",
                    ("sorprendida", true) => "sorprendido",
                    ("pensativa", true) => "pensativo",
                    ("enamorada", true) => "enamorado",
                    ("nerviosa", true) => "nervioso",
                    ("asustada", true) => "asustado",
                    ("confundida", true) => "confundido",
                    (other, _) => other,
                };
                parts.push(format!("hace {mins} min te sentiste {word}"));
            }
        }
        if parts.is_empty() {
            return String::new();
        }
        format!(
            "(Tu ánimo: {}. Que se note un poco en cómo respondes, sin decirlo salvo que venga al caso.)",
            parts.join("; ")
        )
    }

    pub fn public(&self, base_mood: &str) -> Value {
        let now = now_secs();
        let st = self.state.lock().unwrap();
        let (v, a) = Self::now_va(&st, base_mood, now);
        let closest = VA
            .iter()
            .min_by(|(_, v1, a1), (_, v2, a2)| {
                let d1 = (v1 - v).hypot(a1 - a);
                let d2 = (v2 - v).hypot(a2 - a);
                d1.partial_cmp(&d2).unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(k, _, _)| *k)
            .unwrap_or("neutral");
        json!({
            "valence": (v * 100.0).round() / 100.0,
            "energy": (a * 100.0).round() / 100.0,
            "emotion": closest,
        })
    }

    pub fn reset(&self) {
        let mut st = self.state.lock().unwrap();
        *st = MoodState::default();
        let _ = fs::remove_file(&self.file);
    }
}

pub fn since_last_talk(last_ts: Option<f64>) -> String {
    let Some(ts) = last_ts else {
        return String::new();
    };
    let gap = (now_secs() - ts).max(0.0);
    if gap < 6.0 * 3600.0 {
        return String::new();
    }
    if gap < 36.0 * 3600.0 {
        return "(La última vez que hablaron fue hace unas horas, ayer o anoche.)".to_string();
    }
    let days = (gap / 86400.0).round() as u64;
    format!("(La última vez que hablaron fue hace {days} días.)")
}
