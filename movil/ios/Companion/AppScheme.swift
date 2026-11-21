import Foundation
import UniformTypeIdentifiers
import WebKit

/// Sirve la carpeta `www` del paquete (web/, movil/core, los .vrm incluidos) en app://companion/.
final class AppScheme: NSObject, WKURLSchemeHandler {
    static let scheme = "app"
    static let root = Bundle.main.resourceURL?.appendingPathComponent("www", isDirectory: true)
    static let propios: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("companion/vrm", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var v = dir
        var r = URLResourceValues(); r.isExcludedFromBackup = false
        try? v.setResourceValues(r)
        return dir
    }()

    /// Nombre de archivo seguro para un VRM propio (el id lo pone el núcleo: a-z, 0-9, - y _).
    static func propio(_ id: String) throws -> URL {
        guard id.range(of: "^[a-z0-9_-]{1,60}$", options: .regularExpression) != nil else { throw BridgeError("Identificador no válido") }
        return propios.appendingPathComponent("\(id).vrm")
    }

    private static let types: [String: String] = [
        "html": "text/html", "js": "text/javascript", "mjs": "text/javascript", "css": "text/css",
        "json": "application/json", "wav": "audio/wav", "vrm": "application/octet-stream",
        "glb": "model/gltf-binary", "png": "image/png", "svg": "image/svg+xml", "woff2": "font/woff2",
    ]

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url, let root = Self.root else {
            task.didFailWithError(URLError(.badURL)); return
        }
        var path = url.path.isEmpty || url.path == "/" ? "/index.html" : url.path
        path = path.removingPercentEncoding ?? path
        // Los VRM propios (Ajustes › Personaje) viven fuera del paquete, en la carpeta de la app.
        var base = root
        if path.hasPrefix("/propios/") {
            base = Self.propios
            path = String(path.dropFirst("/propios".count))
        }
        let file = base.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        // Nada fuera de su carpeta (por ejemplo «../»).
        guard file.path.hasPrefix(base.standardizedFileURL.path + "/"), let data = try? Data(contentsOf: file) else {
            let body = Data("No encontrado".utf8)
            task.didReceive(HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1",
                                            headerFields: ["Content-Type": "text/plain"])!)
            task.didReceive(body)
            task.didFinish()
            return
        }
        let ext = file.pathExtension.lowercased()
        let type = Self.types[ext] ?? UTType(filenameExtension: ext)?.preferredMIMEType ?? "application/octet-stream"
        let headers = ["Content-Type": type, "Content-Length": String(data.count), "Cache-Control": "no-cache"]
        task.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}
