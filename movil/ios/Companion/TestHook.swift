#if DEBUG
import Foundation
import WebKit

/// Solo en compilaciones de depuración: para probar en el simulador sin teclado. Si aparece Documents/prueba.js en
/// el contenedor de la app, se ejecuta en la página (como cuerpo de una función async) y el resultado va a
/// Documents/prueba.out. La versión que se instala en el iPhone para usarla de verdad (Release) no lo trae.
@MainActor
final class TestHook {
    private weak var webView: WKWebView?
    private var timer: Timer?
    private let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]

    init(webView: WKWebView) {
        self.webView = webView
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll() }
        }
    }

    private func poll() {
        let script = docs.appendingPathComponent("prueba.js")
        guard let code = try? String(contentsOf: script, encoding: .utf8) else { return }
        try? FileManager.default.removeItem(at: script)
        let out = docs.appendingPathComponent("prueba.out")
        webView?.callAsyncJavaScript(code, arguments: [:], in: nil, in: .page) { result in
            let text: String
            switch result {
            case .success(let value):
                if let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]) {
                    text = String(data: data, encoding: .utf8) ?? "\(value)"
                } else {
                    text = "\(value)"
                }
            case .failure(let error):
                text = "ERROR: \(error)"
            }
            try? text.write(to: out, atomically: true, encoding: .utf8)
        }
    }
}
#endif
