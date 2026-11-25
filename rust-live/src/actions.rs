use crate::config::AppConfig;
use crate::play::plain;
use chrono::Local;
use regex::Regex;
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
#[cfg(not(windows))]
use std::process::Command;
use std::time::{Duration, Instant};
use uuid::Uuid;

pub const MAX_PER_REPLY: usize = 3;
const TIMER_MAX_S: u64 = 12 * 3600;
const SEARCH_BUDGET_S: f64 = 4.0;
const SEARCH_MAX: usize = 8;

pub fn catalog_titles() -> Value {
    json!({
        "abrir_app": "Abrir una aplicación",
        "abrir_web": "Abrir una página web",
        "abrir_carpeta": "Abrir una carpeta",
        "buscar_archivo": "Buscar archivos por nombre",
        "temporizador": "Poner un temporizador",
        "multimedia": "Controlar la música o el vídeo",
        "volumen": "Cambiar el volumen",
    })
}

pub fn action_title(name: &str) -> Option<&'static str> {
    match name {
        "abrir_app" => Some("Abrir una aplicación"),
        "abrir_web" => Some("Abrir una página web"),
        "abrir_carpeta" => Some("Abrir una carpeta"),
        "buscar_archivo" => Some("Buscar archivos por nombre"),
        "temporizador" => Some("Poner un temporizador"),
        "multimedia" => Some("Controlar la música o el vídeo"),
        "volumen" => Some("Cambiar el volumen"),
        _ => None,
    }
}

#[derive(Debug, Clone)]
pub struct ActionConfig {
    pub enabled: bool,
    pub ask: bool,
    pub full: bool,
    pub always: Vec<String>,
}

pub fn get_config(cfg: &AppConfig) -> ActionConfig {
    let s = cfg.load_settings();
    let c = s.get("actions").and_then(|v| v.as_object());
    let enabled = c.and_then(|o| o.get("enabled")).and_then(|v| v.as_bool()).unwrap_or(true);
    let full = c.and_then(|o| o.get("full")).and_then(|v| v.as_bool()).unwrap_or(false);
    let ask = c.and_then(|o| o.get("ask")).and_then(|v| v.as_bool()).unwrap_or(false) && !full;
    let always = c
        .and_then(|o| o.get("always"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .filter(|a| action_title(a).is_some())
                .map(|a| a.to_string())
                .collect()
        })
        .unwrap_or_default();
    ActionConfig {
        enabled,
        ask,
        full,
        always,
    }
}

pub fn save_config(
    cfg: &AppConfig,
    enabled: Option<bool>,
    ask: Option<bool>,
    full: Option<bool>,
    add_always: Option<&str>,
    forget_always: Option<&str>,
) -> ActionConfig {
    let mut c = get_config(cfg);
    if let Some(v) = full {
        c.full = v;
    }
    if let Some(v) = enabled {
        c.enabled = v;
    }
    if let Some(v) = ask {
        c.ask = v;
    }
    if let Some(a) = add_always {
        if action_title(a).is_some() && !c.always.iter().any(|x| x == a) {
            c.always.push(a.to_string());
        }
    }
    if let Some(a) = forget_always {
        c.always.retain(|x| x != a);
    }
    cfg.update_settings(|obj| {
        obj.insert(
            "actions".into(),
            json!({
                "enabled": c.enabled,
                "ask": c.ask,
                "full": c.full,
                "always": c.always,
            }),
        );
    });
    c
}

pub fn public_state(cfg: &AppConfig) -> Value {
    let c = get_config(cfg);
    json!({
        "enabled": c.enabled,
        "ask": c.ask,
        "full": c.full,
        "always": c.always,
        "available": true,
        "catalog": catalog_titles(),
    })
}

pub fn history(cfg: &AppConfig, limit: usize) -> Vec<Value> {
    use std::io::{Read, Seek, SeekFrom};
    let path = cfg.data_dir.join("acciones.jsonl");
    let Ok(mut f) = fs::File::open(&path) else {
        return vec![];
    };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    if len > 32768 {
        let _ = f.seek(SeekFrom::End(-32768));
    }
    let mut buf = Vec::new();
    if f.read_to_end(&mut buf).is_err() {
        return vec![];
    }
    let text = String::from_utf8_lossy(&buf);
    let lines_iter: Box<dyn Iterator<Item = &str>> = if len > 32768 {
        Box::new(text.lines().skip(1))
    } else {
        Box::new(text.lines())
    };
    let mut items: Vec<Value> = lines_iter
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .collect();
    items.reverse();
    items.truncate(limit);
    items
}

pub fn log_entry(cfg: &AppConfig, action: &str, detail: &str, decision: &str, result: &str) {
    let path = cfg.data_dir.join("acciones.jsonl");
    let safe_res = if action == "portapapeles" {
        "(contenido del portapapeles omitido)".to_string()
    } else {
        result.chars().take(300).collect::<String>()
    };
    let entry = json!({
        "when": Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
        "action": action,
        "detail": detail.chars().take(300).collect::<String>(),
        "decision": decision,
        "result": safe_res,
    });
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(f, "{}", entry);
    }
}

#[derive(Debug, Clone)]
pub struct PreparedAction {
    pub id: String,
    pub name: String,
    pub title: String,
    pub detail: String,
    pub arg1: String,
    pub arg2: String,
    pub timer_secs: Option<u64>,
}

impl PreparedAction {
    pub fn public(&self, cfg: &AppConfig) -> Value {
        let c = get_config(cfg);
        json!({
            "id": self.id,
            "action": self.name,
            "title": self.title,
            "detail": self.detail,
            "note": "",
            "always": c.always.iter().any(|x| x == &self.name),
            "no_always": false,
        })
    }
}

pub fn prepare(raw_name: &str, arg1: &str, arg2: &str) -> Result<PreparedAction, String> {
    let name = plain(raw_name).replace(' ', "_");
    let title = action_title(&name)
        .ok_or_else(|| format!("Acción no soportada en modo ligero: {name}"))?
        .to_string();
    let a1 = arg1.trim().to_string();
    let a2 = arg2.trim().to_string();
    if a1.is_empty() {
        return Err("Falta el argumento principal de la acción.".into());
    }

    let mut timer_secs = None;
    let detail = match name.as_str() {
        "abrir_app" => format!("Abrir «{a1}»"),
        "abrir_web" => {
            let url = normalize_web(&a1);
            format!("Abrir {url}")
        }
        "abrir_carpeta" => {
            let p = resolve_folder(&a1)?;
            format!("Abrir carpeta {}", p.display())
        }
        "buscar_archivo" => format!("Buscar archivos con «{a1}»"),
        "temporizador" => {
            let secs = parse_duration(&a1)?;
            timer_secs = Some(secs);
            if a2.is_empty() {
                format!("Temporizador de {}", fmt_duration(secs))
            } else {
                format!("Temporizador de {} ({a2})", fmt_duration(secs))
            }
        }
        "multimedia" => format!("Multimedia: {a1}"),
        "volumen" => format!("Volumen: {a1}"),
        _ => return Err("Acción desconocida".into()),
    };

    Ok(PreparedAction {
        id: Uuid::new_v4().simple().to_string()[..12].to_string(),
        name,
        title,
        detail,
        arg1: a1,
        arg2: a2,
        timer_secs,
    })
}

pub fn execute(act: &PreparedAction) -> Result<String, String> {
    match act.name.as_str() {
        "abrir_app" => exec_open_app(&act.arg1),
        "abrir_web" => exec_open_url(&normalize_web(&act.arg1)),
        "abrir_carpeta" => {
            let p = resolve_folder(&act.arg1)?;
            exec_open_path(&p)
        }
        "buscar_archivo" => exec_search_files(&act.arg1),
        "temporizador" => Ok(format!("Temporizador activado ({}).", act.detail)),
        "multimedia" => exec_media(&act.arg1),
        "volumen" => exec_volume(&act.arg1),
        _ => Err("Acción no disponible".into()),
    }
}

fn normalize_web(raw: &str) -> String {
    let s = raw.trim();
    if s.starts_with("https://") || s.starts_with("http://") {
        s.to_string()
    } else if s.contains('.') && !s.contains(' ') {
        format!("https://{s}")
    } else {
        let q: String = s
            .bytes()
            .map(|b| match b {
                b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' => (b as char).to_string(),
                b' ' => "+".to_string(),
                other => format!("%{other:02X}"),
            })
            .collect();
        format!("https://www.google.com/search?q={q}")
    }
}

fn user_home() -> PathBuf {
    std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

pub fn resolve_folder(raw: &str) -> Result<PathBuf, String> {
    let trimmed = raw.trim();
    // Freno crítico de seguridad: rechazar rutas de red UNC antes de tocar el sistema de archivos (evita fugas SMB/NTLM).
    if trimmed.starts_with(r"\\") || trimmed.starts_with("//") {
        return Err("Por seguridad no abro rutas de red.".into());
    }
    let home = user_home();
    let k = plain(trimmed);
    let candidate = match k.as_str() {
        "escritorio" | "desktop" => home.join("Desktop"),
        "descargas" | "downloads" => home.join("Downloads"),
        "documentos" | "documents" => home.join("Documents"),
        "imagenes" | "fotos" | "pictures" => home.join("Pictures"),
        "musica" | "music" => home.join("Music"),
        "videos" | "video" => home.join("Videos"),
        "inicio" | "usuario" | "home" => home.clone(),
        _ => {
            let p = PathBuf::from(trimmed);
            if p.to_string_lossy().starts_with(r"\\") || p.to_string_lossy().starts_with("//") {
                return Err("Por seguridad no abro rutas de red.".into());
            }
            if p.is_dir() {
                p
            } else {
                home.join(trimmed)
            }
        }
    };
    if candidate.to_string_lossy().starts_with(r"\\") || candidate.to_string_lossy().starts_with("//") {
        return Err("Por seguridad no abro rutas de red.".into());
    }
    if candidate.is_dir() {
        Ok(candidate)
    } else {
        Err(format!("No encontré la carpeta «{raw}»."))
    }
}

fn parse_duration(raw: &str) -> Result<u64, String> {
    let s = plain(raw);
    let re = Regex::new(r"(\d+)\s*(h|hr|hrs|hora|horas|m|min|mins|minuto|minutos|s|seg|segs|segundo|segundos)?").unwrap();
    let mut total: u64 = 0;
    for cap in re.captures_iter(&s) {
        let n: u64 = cap[1].parse().unwrap_or(0);
        let unit = cap.get(2).map(|m| m.as_str()).unwrap_or("m");
        total += match unit {
            u if u.starts_with('h') => n * 3600,
            u if u.starts_with('s') => n,
            _ => n * 60,
        };
    }
    if total == 0 || total > TIMER_MAX_S {
        return Err("La duración del temporizador debe ser entre 1 segundo y 12 horas.".into());
    }
    Ok(total)
}

pub fn fmt_duration(secs: u64) -> String {
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    let s = secs % 60;
    let mut parts = Vec::new();
    if h > 0 { parts.push(format!("{h} h")); }
    if m > 0 { parts.push(format!("{m} min")); }
    if s > 0 || parts.is_empty() { parts.push(format!("{s} s")); }
    parts.join(" ")
}

#[cfg(windows)]
fn shell_open_win32(target: &str) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null;
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let op: Vec<u16> = std::ffi::OsStr::new("open").encode_wide().chain(std::iter::once(0)).collect();
    let file: Vec<u16> = std::ffi::OsStr::new(target).encode_wide().chain(std::iter::once(0)).collect();
    let res = unsafe {
        ShellExecuteW(
            null::<core::ffi::c_void>() as _,
            op.as_ptr(),
            file.as_ptr(),
            null(),
            null(),
            SW_SHOWNORMAL,
        )
    };
    if (res as isize) <= 32 {
        return Err(format!("Windows no pudo abrir «{target}» (código {}).", res as isize));
    }
    Ok(())
}

pub fn open_url_safe(url: &str) -> Result<String, String> {
    let u = url.trim();
    if (!u.starts_with("https://") && !u.starts_with("http://"))
        || u.chars().any(|c| c.is_control() || matches!(c, ' ' | '"' | '<' | '>' | '|'))
    {
        return Err("Solo se permiten direcciones http:// o https:// válidas".into());
    }
    #[cfg(windows)]
    {
        shell_open_win32(u)?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open").arg(u).spawn().map_err(|e| e.to_string())?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open").arg(u).spawn().map_err(|e| e.to_string())?;
    }
    Ok(format!("Abierto {u}"))
}

fn exec_open_url(url: &str) -> Result<String, String> {
    open_url_safe(url)
}

fn exec_open_path(path: &Path) -> Result<String, String> {
    #[cfg(windows)]
    {
        shell_open_win32(&path.to_string_lossy())?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open").arg(path).spawn().map_err(|e| e.to_string())?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open").arg(path).spawn().map_err(|e| e.to_string())?;
    }
    Ok(format!("Abierta la carpeta {}", path.display()))
}

fn exec_open_app(name: &str) -> Result<String, String> {
    let k = plain(name);
    #[cfg(windows)]
    {
        let alias = match k.as_str() {
            "calculadora" | "calculator" => Some("calc.exe"),
            "bloc de notas" | "notepad" => Some("notepad.exe"),
            "paint" => Some("mspaint.exe"),
            "explorador" | "explorer" => Some("explorer.exe"),
            "configuracion" | "ajustes" | "settings" => Some("ms-settings:"),
            "chrome" | "google chrome" => Some("chrome.exe"),
            "edge" | "microsoft edge" => Some("msedge.exe"),
            "firefox" => Some("firefox.exe"),
            "spotify" => Some("spotify:"),
            "apple music" => Some("music:"),
            "discord" => Some("discord:"),
            "steam" => Some("steam:"),
            "vscode" | "visual studio code" | "code" => Some("code"),
            "word" => Some("winword.exe"),
            "excel" => Some("excel.exe"),
            "powerpoint" => Some("powerpnt.exe"),
            _ => None,
        };
        if let Some(target) = alias {
            shell_open_win32(target)?;
            return Ok(format!("Abierta {name}"));
        }
        // Search Start Menu .lnk shortcuts
        if let Some(lnk) = find_start_menu_shortcut(&k) {
            shell_open_win32(&lnk.to_string_lossy())?;
            return Ok(format!("Abierta {name}"));
        }
        return Err(format!("No encontré la aplicación «{name}»."));
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .args(["-a", name])
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(format!("Abierta {name}"))
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new(name).spawn().map_err(|e| e.to_string())?;
        Ok(format!("Abierta {name}"))
    }
}

#[cfg(windows)]
fn find_start_menu_shortcut(query_plain: &str) -> Option<PathBuf> {
    let mut roots = Vec::new();
    if let Ok(pd) = std::env::var("PROGRAMDATA") {
        roots.push(PathBuf::from(pd).join(r"Microsoft\Windows\Start Menu\Programs"));
    }
    if let Ok(ad) = std::env::var("APPDATA") {
        roots.push(PathBuf::from(ad).join(r"Microsoft\Windows\Start Menu\Programs"));
    }
    let mut stack = roots;
    while let Some(dir) = stack.pop() {
        let Ok(entries) = fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("lnk")).unwrap_or(false) {
                if let Some(stem) = p.file_stem().and_then(|s| s.to_str()) {
                    if plain(stem).contains(query_plain) {
                        return Some(p);
                    }
                }
            }
        }
    }
    None
}

fn exec_search_files(query: &str) -> Result<String, String> {
    let q = plain(query);
    let home = user_home();
    let roots = ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"];
    let start = Instant::now();
    let mut found = Vec::new();

    for r in roots {
        let mut stack = vec![(home.join(r), 0usize)];
        while let Some((dir, depth)) = stack.pop() {
            if start.elapsed() > Duration::from_secs_f64(SEARCH_BUDGET_S) || found.len() >= SEARCH_MAX {
                break;
            }
            if depth > 4 {
                continue;
            }
            let Ok(entries) = fs::read_dir(&dir) else { continue };
            for entry in entries.flatten() {
                let p = entry.path();
                if let Some(name) = p.file_name().and_then(|n| n.to_str()) {
                    if name.starts_with('.') {
                        continue;
                    }
                    if plain(name).contains(&q) {
                        found.push(p.display().to_string());
                        if found.len() >= SEARCH_MAX {
                            break;
                        }
                    }
                    if p.is_dir() {
                        stack.push((p, depth + 1));
                    }
                }
            }
        }
    }
    if found.is_empty() {
        Ok(format!("No encontré archivos que coincidan con «{query}»."))
    } else {
        Ok(format!("Encontrados ({}):\n{}", found.len(), found.join("\n")))
    }
}

#[cfg(windows)]
fn send_vk(vk: u16) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{keybd_event, KEYEVENTF_KEYUP};
    unsafe {
        keybd_event(vk as u8, 0, 0, 0);
        keybd_event(vk as u8, 0, KEYEVENTF_KEYUP, 0);
    }
}

fn exec_media(cmd: &str) -> Result<String, String> {
    let k = plain(cmd);
    #[cfg(windows)]
    {
        let vk: u16 = match k.as_str() {
            "pausa" | "pausar" | "play" | "reproducir" | "continuar" | "reanudar" => 0xB3,
            "siguiente" | "next" | "saltar" => 0xB0,
            "anterior" | "prev" | "atras" => 0xB1,
            "detener" | "stop" => 0xB2,
            _ => return Err(format!("Orden multimedia no reconocida: {cmd}")),
        };
        send_vk(vk);
        Ok(format!("Multimedia: {cmd}"))
    }
    #[cfg(not(windows))]
    {
        let _ = k;
        Err("El control multimedia rápido solo está disponible en Windows.".into())
    }
}

fn exec_volume(cmd: &str) -> Result<String, String> {
    let k = plain(cmd);
    #[cfg(windows)]
    {
        if k.contains("silenci") || k.contains("mute") {
            send_vk(0xAD);
            return Ok("Silencio alternado.".into());
        }
        if k.contains("sub") || k.contains("up") || k.contains("mas") {
            for _ in 0..5 { send_vk(0xAF); }
            return Ok("Volumen subido.".into());
        }
        if k.contains("baj") || k.contains("down") || k.contains("menos") {
            for _ in 0..5 { send_vk(0xAE); }
            return Ok("Volumen bajado.".into());
        }
        Err(format!("Orden de volumen no reconocida: {cmd}"))
    }
    #[cfg(not(windows))]
    {
        let _ = k;
        Err("El control de volumen solo está disponible en Windows.".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_unc_network_paths() {
        assert!(resolve_folder(r"\\192.168.1.10\share").is_err());
        assert!(resolve_folder("//attacker.example/share").is_err());
    }

    #[test]
    fn rejects_unsafe_urls() {
        assert!(open_url_safe("file:///C:/Windows/System32/calc.exe").is_err());
        assert!(open_url_safe("https://example.com/hola\"&calc").is_err());
    }
}
