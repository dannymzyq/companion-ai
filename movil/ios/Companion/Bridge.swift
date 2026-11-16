import Foundation
import OSLog
import WebKit

let webLog = Logger(subsystem: "local.companion", category: "web")

/// Puente JS ↔ nativo (movil/core/platform.js). Cada mensaje es {cmd, args} y la respuesta {value} o {error}.
/// Los flujos (respuestas por líneas del LLM) mandan eventos con window.__native.event(id, kind, data).
@MainActor
final class Bridge: NSObject, WKScriptMessageHandlerWithReply, WKUIDelegate {
    weak var webView: WKWebView?
    private var streams: [Int: Task<Void, Never>] = [:]
    #if DEBUG
    var testHook: TestHook?
    #endif

    private static let kvDir: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("companion/kv", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void) {
        guard let body = message.body as? [String: Any], let cmd = body["cmd"] as? String else {
            replyHandler(["error": "Mensaje no válido"], nil); return
        }
        let args = body["args"] as? [String: Any] ?? [:]
        Task { @MainActor in
            do {
                let value = try await self.handle(cmd, args)
                replyHandler(["value": value ?? NSNull()], nil)
            } catch {
                replyHandler(["error": (error as? BridgeError)?.message ?? error.localizedDescription], nil)
            }
        }
    }

    private func handle(_ cmd: String, _ a: [String: Any]) async throws -> Any? {
        switch cmd {
        case "app.info":
            #if targetEnvironment(simulator)
            let simulator = true
            #else
            let simulator = false
            #endif
            return ["platform": "ios", "simulator": simulator,
                    "version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] ?? "",
                    "can": ["LIGHT_VOICE": false]]
        case "log":
            webLog.log("[web \(a["level"] as? String ?? "", privacy: .public)] \(a["text"] as? String ?? "", privacy: .public)")
            return true
        case "kv.get":
            let url = try kvURL(a["key"])
            return try? String(contentsOf: url, encoding: .utf8)
        case "kv.set":
            let url = try kvURL(a["key"])
            try (a["value"] as? String ?? "null").write(to: url, atomically: true, encoding: .utf8)
            return true
        case "secret.has":
            return Keychain.has(try secretName(a["name"]))
        case "secret.set":
            let name = try secretName(a["name"])
            guard let value = (a["value"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty else {
                throw BridgeError("Clave vacía")
            }
            return Keychain.set(name, value)
        case "secret.remove":
            Keychain.remove(try secretName(a["name"]))
            return true
        case "http.request":
            let req = try request(a)
            let (data, response) = try await URLSession.shared.data(for: req)
            return ["status": (response as? HTTPURLResponse)?.statusCode ?? 0,
                    "body": String(data: data, encoding: .utf8) ?? ""]
        case "http.stream":
            guard let id = a["stream"] as? Int else { throw BridgeError("Falta el id del flujo") }
            let req = try request(a)
            streams[id] = Task { @MainActor [weak self] in await self?.runStream(id, req) }
            return true
        case "ws.collect":
            guard let s = a["url"] as? String, let url = URL(string: s), url.scheme == "wss" else {
                throw BridgeError("Solo se permiten direcciones wss://")
            }
            do {
                let audio = try await SocketCollect.run(url: url, headers: a["headers"] as? [String: String] ?? [:],
                                                        messages: a["messages"] as? [String] ?? [],
                                                        endPath: a["endPath"] as? String ?? "turn.end",
                                                        timeout: (a["timeout"] as? Double) ?? 20)
                return ["audio": audio.base64EncodedString()]
            } catch let f as SocketCollect.Failure {
                return ["error": f.message, "date": f.serverDate as Any]
            }
        case "stream.cancel":
            if let id = a["id"] as? Int { streams.removeValue(forKey: id)?.cancel() }
            return true
        default:
            throw BridgeError("Orden desconocida: \(cmd)")
        }
    }

    /// El micrófono para la propia interfaz (app://companion) se concede sin otra pregunta: iOS ya pide el
    /// permiso del sistema la primera vez. La cámara no se usa en el teléfono.
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping @MainActor @Sendable (WKPermissionDecision) -> Void) {
        decisionHandler(origin.protocol == AppScheme.scheme && type == .microphone ? .grant : .deny)
    }

    private func runStream(_ id: Int, _ req: URLRequest) async {
        defer { streams.removeValue(forKey: id) }
        let t0 = Date()
        let host = req.url?.host ?? ""
        do {
            let (bytes, response) = try await URLSession.shared.bytes(for: req)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            webLog.log("flujo \(id) \(host, privacy: .public): \(status) a los \(Date().timeIntervalSince(t0), format: .fixed(precision: 2)) s")
            emit(id, "head", ["status": status, "id": id])
            var n = 0
            for try await line in bytes.lines {
                if Task.isCancelled { return }
                n += 1
                if n == 1 { webLog.log("flujo \(id): primera línea a los \(Date().timeIntervalSince(t0), format: .fixed(precision: 2)) s") }
                emit(id, "line", line)
            }
            webLog.log("flujo \(id): fin a los \(Date().timeIntervalSince(t0), format: .fixed(precision: 2)) s (\(n) líneas)")
            emit(id, "end", NSNull())
        } catch is CancellationError {
            emit(id, "end", NSNull())
        } catch {
            webLog.log("flujo \(id): error a los \(Date().timeIntervalSince(t0), format: .fixed(precision: 2)) s: \((error as NSError).code)")
            emit(id, "error", "Sin conexión (\((error as NSError).code))")
        }
    }

    private func emit(_ id: Int, _ kind: String, _ data: Any) {
        guard let json = try? JSONSerialization.data(withJSONObject: [data], options: [.fragmentsAllowed]),
              let text = String(data: json, encoding: .utf8) else { return }
        webView?.evaluateJavaScript("window.__native.event(\(id), \"\(kind)\", \(text)[0])", completionHandler: nil)
    }

    private func request(_ a: [String: Any]) throws -> URLRequest {
        guard let s = a["url"] as? String, let url = URL(string: s), url.scheme == "https" else {
            throw BridgeError("Solo se permiten direcciones https://")
        }
        var req = URLRequest(url: url, timeoutInterval: (a["timeout"] as? Double) ?? 30)
        req.httpMethod = (a["method"] as? String) ?? "GET"
        for (k, v) in a["headers"] as? [String: String] ?? [:] where k.lowercased() != "authorization" {
            req.setValue(v, forHTTPHeaderField: k)
        }
        if let body = a["body"] as? String { req.httpBody = Data(body.utf8) }
        if let mp = a["multipart"] as? [String: Any] {
            // {fields: {k: v}, file: {field, name, mime, base64}}: formulario para subir audio (Groq)
            let boundary = "companion-\(UUID().uuidString)"
            var data = Data()
            func add(_ s: String) { data.append(Data(s.utf8)) }
            for (k, v) in mp["fields"] as? [String: String] ?? [:] {
                add("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n")
            }
            if let f = mp["file"] as? [String: String], let bytes = Data(base64Encoded: f["base64"] ?? "") {
                add("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(f["field"] ?? "file")\"; filename=\"\(f["name"] ?? "audio.wav")\"\r\n")
                add("Content-Type: \(f["mime"] ?? "application/octet-stream")\r\n\r\n")
                data.append(bytes)
                add("\r\n")
            }
            add("--\(boundary)--\r\n")
            req.httpBody = data
            req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        }
        if let bearer = a["bearer"] as? String, !bearer.isEmpty {
            req.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        } else if let auth = a["auth"] as? String {
            guard Keychain.allowed.contains(auth), let key = Keychain.get(auth) else { throw BridgeError("Falta la clave") }
            req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        }
        return req
    }

    private func kvURL(_ key: Any?) throws -> URL {
        guard let k = key as? String, k.range(of: "^[a-z0-9_-]{1,40}$", options: .regularExpression) != nil else {
            throw BridgeError("Nombre no válido")
        }
        return Self.kvDir.appendingPathComponent("\(k).json")
    }

    private func secretName(_ name: Any?) throws -> String {
        guard let n = name as? String, Keychain.allowed.contains(n) else { throw BridgeError("Secreto no permitido") }
        return n
    }
}

struct BridgeError: Error {
    let message: String
    init(_ message: String) { self.message = message }
}
