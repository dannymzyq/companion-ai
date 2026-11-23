use axum::http::{header, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use rust_embed::Embed;
use std::path::Path;

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

pub async fn serve_web_asset(uri: Uri, web_dir: Option<&Path>) -> Response {
    let raw = uri.path().trim_start_matches('/');
    let path = if raw.is_empty() { "index.html" } else { raw };

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

    // 2. Fallback to external web/ directory if present on disk
    if let Some(dir) = web_dir {
        let candidate = dir.join(path);
        if candidate.is_file() {
            if let Ok(bytes) = tokio::fs::read(&candidate).await {
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

    (StatusCode::NOT_FOUND, "No encontrado").into_response()
}
