mod actions;
mod config;
mod desktop;
mod desktop_scene;
mod live;
mod models;
mod mood;
mod personality;
mod play;
mod prompt;
mod server;
mod session;
mod store;

use config::{find_root, AppConfig};
use server::{build_router, AppState};
use std::net::TcpListener;
use std::path::PathBuf;
use tracing::info;

struct CliArgs {
    port: Option<u16>,
    no_window: bool,
    open_browser: bool,
    start_float: bool,
    lite_mode: bool,
    root: Option<PathBuf>,
}

fn parse_args() -> CliArgs {
    let mut args = CliArgs {
        port: None,
        no_window: false,
        open_browser: false,
        start_float: false,
        lite_mode: false,
        root: None,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--port" | "-p" => {
                if let Some(v) = it.next() {
                    args.port = v.parse().ok();
                }
            }
            "--no-window" | "--sin-ventana" => args.no_window = true,
            "--browser" | "--navegador" => {
                args.no_window = true;
                args.open_browser = true;
            }
            "--float" | "--flotante" => args.start_float = true,
            "--lite" | "--ligero" => args.lite_mode = true,
            "--root" => {
                if let Some(v) = it.next() {
                    args.root = Some(PathBuf::from(v));
                }
            }
            "--help" | "-h" => {
                println!(
                    "Companion Live (Rust) — Edición ultra-ligera para Live API\n\n\
                     Uso: companion-live [opciones]\n\
                       --port <N>      Puerto HTTP local (por defecto 8200 o libre)\n\
                       --lite          Modo ultra-ligero (sin 3D/WebGL, mínimo consumo)\n\
                       --float         Abrir directamente en modo flotante\n\
                       --browser       Abrir en el navegador del sistema (sin WebView)\n\
                       --no-window     Solo iniciar el servidor HTTP/WS local\n\
                       --root <RUTA>   Carpeta raíz del proyecto (donde está web/)\n"
                );
                std::process::exit(0);
            }
            _ => {}
        }
    }
    args
}

fn pick_free_port(preferred: u16) -> u16 {
    for p in preferred..preferred.saturating_add(30) {
        if TcpListener::bind(("127.0.0.1", p)).is_ok() {
            return p;
        }
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(preferred)
}

fn open_in_browser(url: &str) {
    #[cfg(windows)]
    let _ = std::process::Command::new("cmd")
        .args(["/C", "start", "", url])
        .spawn();
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(url).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let _ = std::process::Command::new("xdg-open").arg(url).spawn();
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "companion_live=info".into()),
        )
        .init();

    let cli = parse_args();
    let root = find_root(cli.root);
    let preferred_port = cli
        .port
        .or_else(|| std::env::var("PORT").ok().and_then(|v| v.parse().ok()))
        .unwrap_or(8200);
    let port = pick_free_port(preferred_port);

    let cfg = AppConfig::load(root.clone(), port, cli.lite_mode);
    let lite_active = cfg.is_lite();
    let state = AppState::new(cfg);
    let shutdown_rx_win = state.shutdown_tx.subscribe();
    let mut shutdown_rx_srv = state.shutdown_tx.subscribe();

    let url = {
        let mut qs = Vec::new();
        if cli.start_float {
            qs.push("flotante=1");
        }
        if lite_active {
            qs.push("lite=1");
        }
        if qs.is_empty() {
            format!("http://127.0.0.1:{port}/")
        } else {
            format!("http://127.0.0.1:{port}/?{}", qs.join("&"))
        }
    };

    info!(
        "Companion Live (Rust) escuchando en {} (raíz: {})",
        url,
        root.display()
    );

    let state_srv = state.clone();
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .worker_threads(2) // Ultra-low memory footprint!
        .build()
        .expect("No se pudo iniciar Tokio");

    let server_handle = rt.spawn(async move {
        let app = build_router(state_srv);
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", port))
            .await
            .expect("No se pudo abrir el puerto local");
        let _ = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                let _ = shutdown_rx_srv.recv().await;
            })
            .await;
    });

    if cli.no_window {
        if cli.open_browser {
            open_in_browser(&url);
        }
        rt.block_on(async {
            let _ = server_handle.await;
        });
    } else {
        if let Err(err) = desktop::run_window(url.clone(), cli.start_float, shutdown_rx_win) {
            eprintln!("No se pudo abrir la ventana nativa ({err}). Abriendo en el navegador...");
            open_in_browser(&url);
            rt.block_on(async {
                let _ = server_handle.await;
            });
        } else {
            let _ = state.shutdown_tx.send(());
        }
    }
}
