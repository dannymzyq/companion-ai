use serde_json::{json, Value};
use std::sync::Arc;
use tao::dpi::{LogicalPosition, LogicalSize, PhysicalPosition};
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::window::WindowBuilder;
use tokio::sync::broadcast;
use wry::WebViewBuilder;

#[derive(Debug)]
enum UserEvent {
    Ipc(String),
    Shutdown,
}

const DESKTOP_INIT_SCRIPT: &str = r#"
(function() {
  if (window.desktop) return;
  const modeListeners = [];
  const petListeners = [];
  let currentMode = new URLSearchParams(location.search).has('flotante') ? 'float' : 'window';

  window.__rustDesktopDispatch = function(ev) {
    if (!ev || typeof ev !== 'object') return;
    if (ev.type === 'mode') {
      currentMode = ev.mode === 'float' ? 'float' : 'window';
      for (const fn of modeListeners) { try { fn(currentMode); } catch {} }
    } else if (ev.type === 'pet') {
      for (const fn of petListeners) { try { fn(ev.payload); } catch {} }
    }
  };

  function post(cmd, payload) {
    try { window.ipc.postMessage(JSON.stringify({ cmd, payload })); } catch {}
  }

  window.desktop = {
    float: (on) => {
      const next = on ? 'float' : 'window';
      post('float', { on: !!on });
      return Promise.resolve(next);
    },
    onMode: (fn) => { if (typeof fn === 'function') modeListeners.push(fn); },
    quit: () => post('quit', {}),
    ignoreMouse: (ignore) => post('ignore-mouse', { ignore: !!ignore }),
    drag: (phase) => post('drag', { phase: String(phase) }),
    resize: (step) => post('resize', { step: step > 0 ? 1 : -1 }),
    info: () => Promise.resolve({ mode: currentMode, engine: 'rust-wry', canAudio: false }),
    shareInfo: () => Promise.resolve(null),
    shareAudioNext: () => Promise.resolve(false),
    pet: {
      prefs: (p) => post('pet:prefs', p),
      anchors: (a) => post('pet:anchors', a),
      state: (s) => post('pet:state', { state: String(s) }),
      work: (m) => post('pet:work', m),
      frame: () => {},
      rest: (on) => post('pet:rest', { on: !!on }),
      on: (fn) => { if (typeof fn === 'function') petListeners.push(fn); },
      info: () => Promise.resolve({ mode: 'stand', engine: 'rust' }),
      testScene: () => {},
      test: () => {},
    },
  };
})();
"#;

pub fn run_window(
    url: String,
    start_float: bool,
    mut shutdown_rx: broadcast::Receiver<()>,
) -> Result<(), String> {
    // Optimize WebView2 for low latency, autoplay without gesture, and smooth background FPS while gaming.
    #[cfg(windows)]
    {
        let existing = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").unwrap_or_default();
        let extra = "--autoplay-policy=no-user-gesture-required \
                     --disable-renderer-backgrounding \
                     --disable-background-timer-throttling \
                     --disable-backgrounding-occluded-windows";
        if !existing.contains("autoplay-policy") {
            let combined = if existing.is_empty() {
                extra.to_string()
            } else {
                format!("{existing} {extra}")
            };
            std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", combined);
        }
    }

    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    // Forward HTTP /api/shutdown to event loop
    let proxy_shutdown = proxy.clone();
    std::thread::spawn(move || {
        let _ = shutdown_rx.blocking_recv();
        let _ = proxy_shutdown.send_event(UserEvent::Shutdown);
    });

    let init_w = if start_float { 340.0 } else { 520.0 };
    let init_h = if start_float { 527.0 } else { 880.0 };

    let window = WindowBuilder::new()
        .with_title("Companion Live (Rust)")
        .with_inner_size(LogicalSize::new(init_w, init_h))
        .with_min_inner_size(LogicalSize::new(220.0, 320.0))
        .with_transparent(true)
        .with_decorations(!start_float)
        .with_always_on_top(start_float)
        .build(&event_loop)
        .map_err(|e| format!("No se pudo crear la ventana: {e}"))?;

    let proxy_ipc = proxy.clone();
    let webview = WebViewBuilder::new()
        .with_url(&url)
        .with_transparent(true)
        .with_initialization_script(DESKTOP_INIT_SCRIPT)
        .with_ipc_handler(move |req| {
            let _ = proxy_ipc.send_event(UserEvent::Ipc(req.body().to_string()));
        })
        .build(&window)
        .map_err(|e| format!("No se pudo iniciar WebView: {e}"))?;

    let mut is_float = start_float;
    let mut drag_offset: Option<(i32, i32)> = None;
    let mut saved_normal_size = LogicalSize::new(520.0, 880.0);
    let mut float_width: f64 = 340.0;
    let window = Arc::new(window);

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::WindowEvent {
                event: WindowEvent::CloseRequested,
                ..
            } => {
                *control_flow = ControlFlow::Exit;
            }
            Event::UserEvent(UserEvent::Shutdown) => {
                *control_flow = ControlFlow::Exit;
            }
            Event::UserEvent(UserEvent::Ipc(raw)) => {
                let Ok(msg) = serde_json::from_str::<Value>(&raw) else {
                    return;
                };
                let cmd = msg.get("cmd").and_then(|v| v.as_str()).unwrap_or("");
                let payload = msg.get("payload").cloned().unwrap_or(Value::Null);
                match cmd {
                    "quit" => {
                        *control_flow = ControlFlow::Exit;
                    }
                    "float" => {
                        let on = payload.get("on").and_then(|v| v.as_bool()).unwrap_or(false);
                        if on != is_float {
                            if !is_float {
                                let sz = window.inner_size().to_logical::<f64>(window.scale_factor());
                                saved_normal_size = LogicalSize::new(sz.width.max(380.0), sz.height.max(560.0));
                            }
                            is_float = on;
                            window.set_decorations(!on);
                            window.set_always_on_top(on);
                            if on {
                                let h = (float_width * 1.55).round();
                                window.set_inner_size(LogicalSize::new(float_width, h));
                            } else {
                                let _ = window.set_ignore_cursor_events(false);
                                window.set_inner_size(saved_normal_size);
                            }
                            let mode_str = if on { "float" } else { "window" };
                            let js = format!(
                                "window.__rustDesktopDispatch && window.__rustDesktopDispatch({})",
                                json!({"type": "mode", "mode": mode_str})
                            );
                            let _ = webview.evaluate_script(&js);
                        }
                    }
                    "ignore-mouse" => {
                        if is_float {
                            let ign = payload.get("ignore").and_then(|v| v.as_bool()).unwrap_or(false);
                            let _ = window.set_ignore_cursor_events(ign);
                        }
                    }
                    "drag" => {
                        if !is_float {
                            return;
                        }
                        let phase = payload.get("phase").and_then(|v| v.as_str()).unwrap_or("");
                        match phase {
                            "start" => {
                                if let (Some((cx, cy)), Ok(pos)) = (cursor_pos(), window.outer_position()) {
                                    drag_offset = Some((cx - pos.x, cy - pos.y));
                                }
                            }
                            "move" => {
                                if let (Some((dx, dy)), Some((cx, cy))) = (drag_offset, cursor_pos()) {
                                    window.set_outer_position(PhysicalPosition::new(cx - dx, cy - dy));
                                }
                            }
                            _ => {
                                drag_offset = None;
                            }
                        }
                    }
                    "resize" => {
                        if !is_float {
                            return;
                        }
                        let step = payload.get("step").and_then(|v| v.as_i64()).unwrap_or(1);
                        let factor = if step > 0 { 1.08 } else { 1.0 / 1.08 };
                        float_width = (float_width * factor).clamp(220.0, 900.0).round();
                        let h = (float_width * 1.55).round();
                        if let Ok(pos) = window.outer_position() {
                            let scale = window.scale_factor();
                            let old_sz = window.inner_size().to_logical::<f64>(scale);
                            let old_pos = pos.to_logical::<f64>(scale);
                            let nx = old_pos.x + (old_sz.width - float_width) / 2.0;
                            let ny = old_pos.y + old_sz.height - h;
                            window.set_inner_size(LogicalSize::new(float_width, h));
                            window.set_outer_position(LogicalPosition::new(nx, ny));
                        } else {
                            window.set_inner_size(LogicalSize::new(float_width, h));
                        }
                    }
                    _ => {}
                }
            }
            _ => {}
        }
    });
}

#[cfg(windows)]
fn cursor_pos() -> Option<(i32, i32)> {
    use windows_sys::Win32::Foundation::POINT;
    use windows_sys::Win32::UI::WindowsAndMessaging::GetCursorPos;
    let mut pt = POINT { x: 0, y: 0 };
    unsafe {
        if GetCursorPos(&mut pt) != 0 {
            Some((pt.x, pt.y))
        } else {
            None
        }
    }
}

#[cfg(not(windows))]
fn cursor_pos() -> Option<(i32, i32)> {
    None
}
