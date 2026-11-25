use axum::http::{header, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use rust_embed::Embed;
use std::path::{Component, Path};

#[derive(Embed)]
#[folder = "../web/"]
pub struct WebAssets;

#[derive(Embed)]
#[folder = "../personas/"]
pub struct PersonaAssets;

pub fn embedded_persona_file(name: &str) -> Option<String> {
    PersonaAssets::get(name)
        .and_then(|f| String::from_utf8(f.data.into_owned()).ok())
}

pub fn is_safe_rel_path(rel: &str) -> bool {
    if rel.is_empty() || rel.contains('\\') || rel.contains('\0') {
        return false;
    }
    Path::new(rel)
        .components()
        .all(|c| matches!(c, Component::Normal(_)))
}

pub async fn serve_web_asset(uri: Uri, web_dir: Option<&Path>) -> Response {
    let raw = uri.path().trim_start_matches('/');
    let path = if raw.is_empty() { "index.html" } else { raw };

    if !is_safe_rel_path(path) {
        return (StatusCode::BAD_REQUEST, "Ruta no permitida").into_response();
    }

    // 1. Prefer embedded in-memory assets (0 disk I/O, 100% portable, instant!)
    if let Some(file) = WebAssets::get(path) {
        let mime = mime_guess::from_path(path).first_or_octet_stream();
        return (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, mime.as_ref().to_string()),
                (header::CACHE_CONTROL, "no-cache".to_string()),
            ],
            file.data.into_owned(),
        )
            .into_response();
    }

    // 2. Fallback to external web/ directory if present on disk (verified inside web_dir)
    if let Some(dir) = web_dir {
        if let Ok(dir_canon) = dir.canonicalize() {
            let candidate = dir_canon.join(path);
            if let Ok(cand_canon) = candidate.canonicalize() {
                if cand_canon.starts_with(&dir_canon) && cand_canon.is_file() {
                    if let Ok(bytes) = tokio::fs::read(&cand_canon).await {
                        let mime = mime_guess::from_path(path).first_or_octet_stream();
                        return (
                            StatusCode::OK,
                            [
                                (header::CONTENT_TYPE, mime.as_ref().to_string()),
                                (header::CACHE_CONTROL, "no-cache".to_string()),
                            ],
                            bytes,
                        )
                            .into_response();
                    }
                }
            }
        }
    }

    (StatusCode::NOT_FOUND, "No encontrado").into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_path_traversal() {
        assert!(is_safe_rel_path("index.html"));
        assert!(is_safe_rel_path("js/main.js"));
        assert!(!is_safe_rel_path("../.env"));
        assert!(!is_safe_rel_path("js/../../data/settings.json"));
        assert!(!is_safe_rel_path(r"js\main.js"));
    }
}
