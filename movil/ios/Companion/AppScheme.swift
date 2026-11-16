import Foundation
import UniformTypeIdentifiers
import WebKit

/// Sirve la carpeta `www` del paquete (web/, movil/core, los .vrm incluidos) en app://companion/.
final class AppScheme: NSObject, WKURLSchemeHandler {
    static let scheme = "app"
    static let root = Bundle.main.resourceURL?.appendingPathComponent("www", isDirectory: true)

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
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        // Nada fuera de www (por ejemplo «../»).
        guard file.path.hasPrefix(root.standardizedFileURL.path + "/"), let data = try? Data(contentsOf: file) else {
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
