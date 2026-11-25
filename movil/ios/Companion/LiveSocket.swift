import AVFoundation
import Foundation

/// WebSocket continuo para el modo «En vivo» (Gemini Live). El protocolo (setup, audio, herramientas) lo arma el
/// núcleo en JS (movil/core/live.js); aquí solo hay transporte. La clave la pone el nativo en la dirección y nunca
/// vuelve al JS, y solo se manda al servidor de la Live API de Google (si no, una dirección inventada se la llevaría).
@MainActor
final class LiveSocket: NSObject, URLSessionWebSocketDelegate {
    static let hosts: Set<String> = ["generativelanguage.googleapis.com"]

    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private let id: Int
    private weak var bridge: Bridge?

    init(id: Int, bridge: Bridge) {
        self.id = id
        self.bridge = bridge
        super.init()
    }

    func open(url: URL, keyName: String?) throws {
        guard url.scheme == "wss", let host = url.host, Self.hosts.contains(host) else {
            throw BridgeError("En vivo solo se conecta a la Live API de Google")
        }
        var comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        comps.queryItems = (comps.queryItems ?? []).filter { $0.name != "key" }
        if comps.queryItems?.isEmpty == true { comps.queryItems = nil }
        var req = URLRequest(url: comps.url!, timeoutInterval: 15)
        if let keyName {
            guard Keychain.allowed.contains(keyName), let key = Keychain.get(keyName) else { throw BridgeError("Falta la clave") }
            req.setValue(key, forHTTPHeaderField: "x-goog-api-key")
        }
        let ses = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        let t = ses.webSocketTask(with: req)
        t.maximumMessageSize = 16 * 1024 * 1024
        session = ses
        task = t
        t.resume()
        receive()
    }

    nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        Task { @MainActor [weak self] in
            guard let self, self.task === webSocketTask else { return }
            self.bridge?.emit(self.id, "open", NSNull())
        }
    }

    func send(_ text: String) async throws {
        guard let task else { throw BridgeError("En vivo no está conectado") }
        try await task.send(.string(text))
    }

    func close() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
    }

    private func receive() {
        task?.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.task != nil else { return }
                switch result {
                case .success(.string(let text)):
                    self.bridge?.emit(self.id, "message", text)
                    self.receive()
                case .success(.data(let data)):          // Gemini manda el JSON también como binario
                    self.bridge?.emit(self.id, "message", String(decoding: data, as: UTF8.self))
                    self.receive()
                case .success:
                    self.receive()
                case .failure(let error):
                    let t = self.task
                    self.task = nil
                    // El motivo del cierre (p. ej. clave no válida o cuota) viene en closeReason; nunca lleva la clave.
                    let reason = t?.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    let code = t?.closeCode.rawValue ?? 0
                    if code == URLSessionWebSocketTask.CloseCode.normalClosure.rawValue {
                        self.bridge?.emit(self.id, "end", NSNull())
                    } else {
                        let why = reason.isEmpty ? "sin conexión (\((error as NSError).code))" : reason
                        self.bridge?.emit(self.id, "error", "En vivo se cortó: \(why)")
                    }
                }
            }
        }
    }

    /// Llamada de voz: con «voiceChat» iOS cancela el eco del altavoz (si no, Gemini se oye a sí mismo y se corta).
    static func audioMode(live: Bool) {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        do {
            if live {
                try s.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
            } else {
                try s.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetoothHFP])
            }
            try s.setActive(true)
        } catch {
            webLog.log("Sesión de audio: \(error.localizedDescription, privacy: .public)")
        }
        #endif
    }
}
