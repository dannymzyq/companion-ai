use serde_json::{json, Value};

#[cfg(windows)]
pub fn foreground() -> Option<Value> {
    use windows_sys::Win32::Foundation::{HWND, RECT};
    use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS};
    use windows_sys::Win32::Graphics::Gdi::{
        GetMonitorInfoW, MonitorFromWindow, MONITORINFO, MONITOR_DEFAULTTONEAREST,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetDesktopWindow, GetForegroundWindow, GetShellWindow, GetWindowRect,
        GetWindowThreadProcessId, IsIconic, IsWindowVisible, IsZoomed,
    };

    unsafe {
        let hwnd: HWND = GetForegroundWindow();
        if hwnd.is_null()
            || hwnd == GetShellWindow()
            || hwnd == GetDesktopWindow()
            || IsWindowVisible(hwnd) == 0
        {
            return None;
        }
        let mut rect = RECT {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        let hr = DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS as u32,
            (&mut rect as *mut RECT).cast(),
            std::mem::size_of::<RECT>() as u32,
        );
        if hr != 0 {
            let _ = GetWindowRect(hwnd, &mut rect);
        }

        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        let own = pid == std::process::id();

        let minimized = IsIconic(hwnd) != 0;
        let maximized = IsZoomed(hwnd) != 0;

        let mut fullscreen = false;
        let mon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
        if !mon.is_null() {
            let mut mi: MONITORINFO = std::mem::zeroed();
            mi.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
            if GetMonitorInfoW(mon, &mut mi) != 0 {
                let mr = mi.rcMonitor;
                fullscreen = !minimized
                    && rect.left <= mr.left + 2
                    && rect.top <= mr.top + 2
                    && rect.right >= mr.right - 2
                    && rect.bottom >= mr.bottom - 2;
            }
        }

        Some(json!({
            "id": hwnd as usize,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "minimized": minimized,
            "maximized": maximized,
            "fullscreen": fullscreen,
            "own": own,
        }))
    }
}

#[cfg(not(windows))]
pub fn foreground() -> Option<Value> {
    None
}
