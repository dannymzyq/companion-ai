import AVFoundation
import Foundation
import OSLog
import WebKit

let webLog = Logger(subsystem: "local.companion", category: "web")

/// Puente JS ↔ nativo (movil/core/platform.js). Cada mensaje es {cmd, args} y la respuesta {value} o {error}.
/// Los flujos (respuestas por líneas del LLM) mandan eventos con window.__native.event(id, kind, data).
@MainActor
final class Bridge: NSObject, WKScriptMessageHandlerWithReply, WKUIDelegate {
    weak var webView: WKWebView?
    var streams: [Int: Task<Void, Never>] = [:]
    var streamCuts: [Int: Corte] = [:]
    var sockets: [Int: LiveSocket] = [:]          // modo «En vivo»
    lazy var flotante: VentanaFlotante = {
        let v = VentanaFlotante()
        v.alCerrar = { [weak self] in self?.webView?.evaluateJavaScript("window.__native.emit('pip', false)", completionHandler: nil) }
        return v
    }()
    lazy var pantalla: ReceptorPantalla = {
        let r = ReceptorPantalla()
        r.alCuadro = { [weak self] jpeg in
            self?.webView?.evaluateJavaScript("window.__native.emit('pantalla', '\(jpeg.base64EncodedString())')", completionHandler: nil)
        }
        r.alCambiar = { [weak self] on in
            self?.flotante.mantenerDespierta = on
            self?.webView?.evaluateJavaScript("window.__native.emit('pantallaEstado', \(on))", completionHandler: nil)
        }
        return r
    }()
    #if DEBUG || PRUEBAS
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
                    "can": Bridge.capacidades()]
        case "mic.permission":
            // Si iOS ya dio permiso al micrófono, la página no vuelve a preguntar al arrancar.
            switch AVAudioApplication.shared.recordPermission {
            case .granted: return "granted"
            case .denied: return "denied"
            default: return "undetermined"
            }
        case "log":
            webLog.log("[web \(a["level"] as? String ?? "", privacy: .public)] \(a["text"] as? String ?? "", privacy: .public)")
            #if PRUEBAS
            // Compilación de pruebas en el iPhone: los tiempos (solo las líneas «info») van a Documents/registro.txt,
            // que se copia al Mac con devicectl. No llevan lo que dice el usuario.
            if a["level"] as? String == "info", let t = a["text"] as? String {
                Registro.anotar(t)
            }
            #endif
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
        case "live.open":
            guard let id = a["stream"] as? Int, let s = a["url"] as? String, let url = URL(string: s) else {
                throw BridgeError("Falta la dirección")
            }
            sockets.removeValue(forKey: id)?.close()
            let sock = LiveSocket(id: id, bridge: self)
            try sock.open(url: url, keyName: a["auth"] as? String)
            sockets[id] = sock
            return true
        case "live.send":
            guard let id = a["id"] as? Int, let text = a["text"] as? String, let sock = sockets[id] else {
                throw BridgeError("En vivo no está conectado")
            }
            try await sock.send(text)
            return true
        case "vrm.write":
            // VRM propio por trozos (base64): el primero crea el archivo, los demás lo amplían.
            let url = try AppScheme.propio(a["id"] as? String ?? "")
            guard let s = a["data"] as? String, let chunk = Data(base64Encoded: s) else { throw BridgeError("Datos no válidos") }
            if a["first"] as? Bool ?? false { try chunk.write(to: url) }
            else {
                let h = try FileHandle(forWritingTo: url)
                defer { try? h.close() }
                try h.seekToEnd()
                try h.write(contentsOf: chunk)
            }
            return true
        case "vrm.remove":
            try? FileManager.default.removeItem(at: try AppScheme.propio(a["id"] as? String ?? ""))
            return true
        case "pip.open":
            guard let web = webView else { throw BridgeError("Sin vista") }
            try flotante.abrir(en: web, ancho: a["width"] as? Int ?? 360, alto: a["height"] as? Int ?? 480)
            // No se abre aquí: se abre sola al salir de la app (iOS no deja que la app se mande a segundo plano).
            return true
        case "pip.frame":
            guard let s = a["jpeg"] as? String, let data = Data(base64Encoded: s) else { throw BridgeError("Cuadro no válido") }
            flotante.cuadro(data)
            return flotante.activa
        case "screen.start":
            // Compartir pantalla: abre la hoja de iOS para transmitir (la extensión manda las imágenes aquí).
            guard let web = webView else { throw BridgeError("Sin vista") }
            try pantalla.escuchar()
            if pantalla.activa { return true }
            ReceptorPantalla.pedirTransmision(en: web)
            return false
        case "screen.stop":
            pantalla.parar()
            return true
        case "pip.close":
            flotante.cerrar()
            return true
        case "audio.mode":
            LiveSocket.audioMode(live: a["live"] as? Bool ?? false)
            return true
        case "stream.cancel":
            if let id = a["id"] as? Int {
                sockets.removeValue(forKey: id)?.close()
                streamCuts.removeValue(forKey: id)?.cortar()
                streams.removeValue(forKey: id)?.cancel()
            }
            return true
        default:
            return try await motores(cmd, a)
        }
    }

    /// El micrófono para la propia interfaz (app://companion) se concede sin otra pregunta: iOS ya pide el
    /// permiso del sistema la primera vez (también para la cámara).
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping @MainActor @Sendable (WKPermissionDecision) -> Void) {
        decisionHandler(origin.protocol == AppScheme.scheme ? .grant : .deny)   // micrófono y cámara
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

    // ---------------------------------------------------------------- teclado
    private var pin: NSKeyValueObservation?
    private var keyboardObservers: [NSObjectProtocol] = []

    /// El teclado se pone ENCIMA de la app: WKWebView desplazaba toda la página para enseñar el campo de texto (el
    /// personaje subía con él). La página queda fija y solo la barra de abajo sube lo que ocupa el teclado
    /// (--teclado en ui_movil.js).
    /// Auriculares que se conectan o desconectan (AirPods, cable, coche): la página vuelve a abrir el micrófono
    /// predeterminado, el que iOS usa en ese momento. La salida sigue sola a la ruta del sistema.
    private var ruta: NSObjectProtocol?
    func watchAudioRoute(_ web: WKWebView) {
        ruta = NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak web] n in
            let r = (n.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt).flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
            guard r == .newDeviceAvailable || r == .oldDeviceUnavailable else { return }
            web?.evaluateJavaScript("window.__native && window.__native.emit('audioRoute', true)", completionHandler: nil)
        }
    }

    func watchKeyboard(_ web: WKWebView) {
        Self.sinBarraDelTeclado(web)
        watchAudioRoute(web)
        pin = web.scrollView.observe(\.contentOffset, options: [.new]) { sv, _ in
            if sv.contentOffset != .zero { DispatchQueue.main.async { sv.contentOffset = .zero } }
        }
        let nc = NotificationCenter.default
        let send: (Notification) -> Void = { [weak self, weak web] n in
            guard let web, let end = n.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            let local = web.convert(end, from: nil)
            let alto = max(0, web.bounds.maxY - local.minY)
            let dur = (n.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double) ?? 0.25
            MainActor.assumeIsolated {
                self?.webView?.evaluateJavaScript(
                    "window.__teclado && window.__teclado(\(Int(alto)), \(dur))", completionHandler: nil)
            }
        }
        keyboardObservers = [
            nc.addObserver(forName: UIResponder.keyboardWillChangeFrameNotification, object: nil, queue: .main, using: send),
            nc.addObserver(forName: UIResponder.keyboardWillHideNotification, object: nil, queue: .main, using: send),
        ]
    }

    /// Quita la barra «^ v ✓» que WKWebView pone encima del teclado (tapaba el chat, que es un solo campo):
    /// la vista interna de WebKit pasa a una subclase hecha en el momento cuyo inputAccessoryView es nil.
    private static func sinBarraDelTeclado(_ web: WKWebView) {
        guard let content = web.scrollView.subviews.first(where: { String(describing: type(of: $0)).hasPrefix("WKContent") }),
              let base: AnyClass = object_getClass(content) else { return }
        let name = "\(NSStringFromClass(base))_SinBarra"
        var sub: AnyClass? = NSClassFromString(name)
        if sub == nil, let c = objc_allocateClassPair(base, name, 0) {
            let block: @convention(block) (AnyObject) -> UIView? = { _ in nil }
            let sel = #selector(getter: UIResponder.inputAccessoryView)
            if let m = class_getInstanceMethod(UIView.self, sel) {
                class_addMethod(c, sel, imp_implementationWithBlock(block), method_getTypeEncoding(m))
            }
            objc_registerClassPair(c)
            sub = c
        }
        if let sub { object_setClass(content, sub) }
    }

    func emit(_ id: Int, _ kind: String, _ data: Any) {
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

#if PRUEBAS
enum Registro {
    static let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("registro.txt")
    static func anotar(_ t: String) {
        let linea = "\(ISO8601DateFormatter().string(from: Date())) \(t)\n"
        if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(linea.utf8)); try? h.close() }
        else { try? linea.write(to: url, atomically: true, encoding: .utf8) }
    }
}
#endif
