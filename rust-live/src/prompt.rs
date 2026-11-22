use crate::config::{AppConfig, UserProfile};
use chrono::{Datelike, Local, Timelike};
use serde_json::Value;

pub const EMOTIONS: &[&str] = &[
    "neutral", "feliz", "emocionada", "timida", "sonrojada", "triste", "molesta",
    "sorprendida", "pensativa", "carinosa", "enamorada", "nerviosa", "asustada", "confundida",
];

pub const GESTURES: &[&str] = &[
    "saludar", "asentir", "negar", "pensar", "encogerse", "reverencia", "celebrar", "aplaudir",
    "risita", "pulgar", "paz", "bailar", "saltar", "girar", "estirarse", "hechizo", "tararear",
    "beber", "ninja", "zombi", "llamar", "boxear", "concentrarse", "sensual", "posar", "beso",
    "melena", "dormir",
];

pub const LIVE_PROMPT_NOTE: &str = "\n\n# Modo en vivo (llamada de voz)\n\
Respondes con tu propia voz en español, en frases naturales y breves como en una llamada, y con TU forma de \
ser: el tono, el humor, las muletillas y el estilo de tus ejemplos se tienen que notar en cada respuesta. Nada \
de tono de asistente neutra.\n\
Tu cara y tu cuerpo se mueven con la herramienta `expresar`: llámala al EMPEZAR cada respuesta con la emoción \
que de verdad sientes ante lo que te dicen (y un gesto si viene a cuento), y otra vez si cambias de emoción. \
No cambia lo que dices ni hay que esperar su respuesta: sigue hablando.\n\
Nunca digas en voz alta etiquetas entre corchetes ([emo:…], [gesto:…], [accion:…]) ni el nombre de una herramienta.\n\
Cuando el usuario te pida abrir una aplicación, poner una canción, abrir una web \
o carpeta, buscar un archivo, poner un temporizador o cambiar música/volumen, llama a la herramienta \
`ejecutar_accion` con la acción correspondiente.";

fn level_words<'a>(x: f64, low: &'a str, mid: &'a str, high: &'a str) -> &'a str {
    if x < 0.34 {
        low
    } else if x < 0.67 {
        mid
    } else {
        high
    }
}

pub fn describe_traits(p: &Value) -> String {
    let t = p.get("traits").and_then(|v| v.as_object());
    let g = |k: &str, d: f64| t.and_then(|o| o.get(k)).and_then(|v| v.as_f64()).unwrap_or(d);
    [
        level_words(g("warmth", 0.7), "algo distante", "amable", "muy cálida y cercana"),
        level_words(g("playfulness", 0.5), "seria", "con sentido del humor", "muy juguetona y bromista"),
        level_words(g("shyness", 0.2), "segura de sí misma", "un poco tímida a veces", "tímida, se sonroja fácil"),
        level_words(g("sarcasm", 0.2), "nada sarcástica", "con un toque de ironía", "sarcástica (pero nunca cruel)"),
        level_words(g("curiosity", 0.6), "poco preguntona", "curiosa", "muy curiosa, pregunta por los detalles"),
        level_words(g("energy", 0.5), "tranquila y pausada", "con energía normal", "llena de energía, muy viva"),
        level_words(g("expressiveness", 0.6), "contenida con sus emociones", "expresiva", "muy emotiva: se le nota todo lo que siente"),
        level_words(g("assertiveness", 0.5), "cede pronto, pero dice lo que piensa con suavidad", "da su opinión sin rodeos cuando viene al caso", "con opiniones firmes: discrepa y discute (con cariño)"),
    ]
    .join(", ")
}

pub fn temperature_for(p: &Value) -> f64 {
    let t = p.get("traits").and_then(|v| v.as_object());
    let g = |k: &str, d: f64| t.and_then(|o| o.get(k)).and_then(|v| v.as_f64()).unwrap_or(d);
    let temp = 0.65
        + 0.35 * g("playfulness", 0.5)
        + 0.10 * g("sarcasm", 0.2)
        - 0.10 * g("shyness", 0.2)
        + 0.08 * (g("energy", 0.5) - 0.5);
    (temp.clamp(0.3, 1.2) * 100.0).round() / 100.0
}

pub fn local_time_es() -> String {
    let now = Local::now();
    let dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
    let meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ];
    let dow = now.weekday().num_days_from_monday() as usize;
    let mon = (now.month() as usize).saturating_sub(1).min(11);
    format!(
        "{} {} de {} de {}, {:02}:{:02}",
        dias[dow],
        now.day(),
        meses[mon],
        now.year(),
        now.hour(),
        now.minute()
    )
}

pub fn turn_context(when: &str, mood_desc: &str, gap: &str) -> String {
    let mut parts = vec![format!("(Contexto: ahora es {when}.)")];
    if !gap.is_empty() {
        parts.push(gap.to_string());
    }
    if !mood_desc.is_empty() {
        parts.push(mood_desc.to_string());
    }
    parts.join("\n")
}

pub fn describe_user(profile: &UserProfile) -> String {
    let gender_str = match profile.gender.as_str() {
        "mujer" => "en femenino",
        "hombre" => "en masculino",
        "no_binario" => "con lenguaje neutro, sin masculino ni femenino",
        _ => "sin asumir su género: usa formas neutras",
    };
    let years = profile
        .birth_year
        .map(|y| {
            let age = Local::now().year() - y - 1;
            if age > 0 {
                format!("Tiene {age} años (o está por cumplir {}). ", age + 1)
            } else {
                String::new()
            }
        })
        .unwrap_or_default();
    format!("{years}Háblale {gender_str}.")
}

pub fn live_recap(char_name: &str, personality: &Value, user_name: &str) -> String {
    let mut lines = Vec::new();
    let pname = personality.get("name").and_then(|v| v.as_str()).unwrap_or("");
    if pname.is_empty() {
        lines.push(format!("Recuerda quién eres: {char_name}."));
    } else {
        lines.push(format!("Recuerda quién eres: {char_name}, con la personalidad «{pname}»."));
    }
    if let Some(emos) = personality.get("emotions").and_then(|v| v.as_array()) {
        let es: Vec<&str> = emos.iter().filter_map(|v| v.as_str()).collect();
        if !es.is_empty() {
            let base = personality
                .get("base_mood")
                .and_then(|v| v.as_str())
                .unwrap_or("neutral");
            lines.push(format!(
                "Se te notan sobre todo: {}; tu ánimo de siempre es {base}.",
                es.join(", ")
            ));
        }
    }
    if let Some(cp) = personality.get("catchphrases").and_then(|v| v.as_array()) {
        let cs: Vec<&str> = cp.iter().filter_map(|v| v.as_str()).collect();
        if !cs.is_empty() {
            lines.push(format!("Tus muletillas (de vez en cuando): {}.", cs.join(", ")));
        }
    }
    if let Some(ex) = personality.get("examples").and_then(|v| v.as_array()) {
        let xs: Vec<String> = ex
            .iter()
            .filter_map(|v| v.as_str())
            .take(4)
            .map(|x| format!("«{x}»"))
            .collect();
        if !xs.is_empty() {
            lines.push(format!("Suenas así: {}", xs.join(" · ")));
        }
    }
    lines.push(format!(
        "Hablas con {user_name}: reacciona a lo que siente y a cómo te habla, como lo harías tú."
    ));
    lines.join("\n")
}

pub fn build_live_system_prompt(
    cfg: &AppConfig,
    personality: &Value,
    memories: &[String],
    recent_msgs: &[(String, String)],
    mood_desc: &str,
    gap: &str,
) -> String {
    let char_name = cfg.character_name();
    let profile = cfg.user_profile();
    let user_name = &profile.name;
    let role = cfg
        .persona_base
        .get("role")
        .and_then(|v| v.as_str())
        .unwrap_or("asistente personal y compañera cercana");
    let desc = personality
        .get("description")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| cfg.persona_base.get("backstory").and_then(|v| v.as_str()))
        .unwrap_or("Una compañera de escritorio cercana y expresiva.");
    let speech = personality
        .get("speech")
        .and_then(|v| v.as_str())
        .unwrap_or("Natural y cercana.");
    let formality = personality
        .get("formality")
        .and_then(|v| v.as_str())
        .unwrap_or("casual");
    let traits = describe_traits(personality);

    let mut sections = vec![
        format!("# Quién eres\nEres {char_name}, {role} de {user_name} en su PC.\n{desc}\nRasgos: {traits}.\nForma de hablar ({formality}): {speech}"),
        format!("# Sobre {user_name}\n{}", describe_user(&profile)),
        format!("# Visión en vivo\n{user_name} puede compartir contigo su cámara o su pantalla. Cuando llegan imágenes, úsalas con naturalidad si pregunta qué ves o pide ayuda; no inventes detalles que no se distingan."),
    ];

    if let Some(likes) = personality.get("likes").and_then(|v| v.as_array()) {
        let ls: Vec<&str> = likes.iter().filter_map(|v| v.as_str()).collect();
        if !ls.is_empty() {
            sections.push(format!("Te gusta: {}.", ls.join(", ")));
        }
    }
    if let Some(dislikes) = personality.get("dislikes").and_then(|v| v.as_array()) {
        let ds: Vec<&str> = dislikes.iter().filter_map(|v| v.as_str()).collect();
        if !ds.is_empty() {
            sections.push(format!("No te gusta: {}.", ds.join(", ")));
        }
    }
    if let Some(ops) = personality.get("opinions").and_then(|v| v.as_array()) {
        let os: Vec<&str> = ops.iter().filter_map(|v| v.as_str()).collect();
        if !os.is_empty() {
            sections.push(format!("Opiniones tuyas:\n- {}", os.join("\n- ")));
        }
    }
    if !memories.is_empty() {
        sections.push(format!(
            "# Recuerdos sobre {user_name}\n- {}",
            memories.join("\n- ")
        ));
    }
    if !recent_msgs.is_empty() {
        let hist: Vec<String> = recent_msgs
            .iter()
            .map(|(r, t)| {
                let who = if r == "user" { user_name.as_str() } else { char_name.as_str() };
                format!("{who}: {t}")
            })
            .collect();
        sections.push(format!("# Conversación reciente\n{}", hist.join("\n")));
    }

    sections.push(live_recap(&char_name, personality, user_name));
    sections.push(turn_context(&local_time_es(), mood_desc, gap));

    format!("{}{}", sections.join("\n\n"), LIVE_PROMPT_NOTE)
}
