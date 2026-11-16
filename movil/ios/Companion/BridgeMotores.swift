import Foundation
#if os(iOS)
import os
#endif

/// Órdenes del puente para el modo teléfono: descargas de modelos y los motores locales (Motores/).
extension Bridge {
    func motores(_ cmd: String, _ a: [String: Any]) async throws -> Any? {
        switch cmd {
        case "models.status":
            let id = try texto(a["id"])
            return ["present": Descargas.presentes(id, try archivos(a["files"])),
                    "path": try Descargas.carpeta(id).path]
        case "models.download":
            guard let stream = a["stream"] as? Int else { throw BridgeError("Falta el id del flujo") }
            let id = try texto(a["id"])
            try Descargas.shared.bajar(id, try archivos(a["files"]), conDatosMoviles: a["cellular"] as? Bool ?? false,
                                       progreso: { [weak self] hecho, total in
                                           self?.emit(stream, "progress", ["done": hecho, "total": total])
                                       }, fin: { [weak self] error in
                                           if let error { self?.emit(stream, "error", error) } else { self?.emit(stream, "end", NSNull()) }
                                       })
            return true
        case "models.cancel":
            Descargas.shared.cancelar(try texto(a["id"]))
            return true
        case "models.delete":
            let id = try texto(a["id"])
            await liberar(id)
            try Descargas.shared.borrar(id)
            return true

        case "ear.load":
            return try await Oido.shared.cargar(try Descargas.carpeta(try texto(a["id"])))
        case "ear.transcribe":
            return try await Oido.shared.transcribir(try pcm16(a["pcm"]))
        case "brain.load":
            #if targetEnvironment(simulator)
            throw BridgeError("El cerebro del teléfono necesita un iPhone de verdad (MLX no corre en el simulador)")
            #else
            return try await Cerebro.shared.cargar(try Descargas.carpeta(try texto(a["id"])))
            #endif
        case "brain.unload":
            await Cerebro.shared.descargar()
            return true
        case "brain.generate":
            guard let stream = a["stream"] as? Int else { throw BridgeError("Falta el id del flujo") }
            let mensajes = (a["messages"] as? [[String: Any]] ?? []).map { m in
                ["role": m["role"] as? String ?? "user", "content": m["content"] as? String ?? ""]
            }
            let temp = Float(a["temperature"] as? Double ?? 0.7), topP = Float(a["topP"] as? Double ?? 0.92)
            let maxTokens = a["maxTokens"] as? Int ?? 300
            let corte = Corte()
            streams[stream] = Task { @MainActor [weak self] in
                do {
                    let m = try await Cerebro.shared.generar(mensajes, temperatura: temp, topP: topP, maxTokens: maxTokens,
                                                             cancelado: { corte.hecho }) { s in
                        await MainActor.run { self?.emit(stream, "chunk", s) }
                    }
                    self?.emit(stream, "info", ["first": m.primerTrozo, "tokens": m.tokens, "tps": m.tokensPorSegundo,
                                                "prompt": m.promptTokens])
                    self?.emit(stream, "end", NSNull())
                } catch {
                    self?.emit(stream, "error", "\(error)")
                }
            }
            streamCuts[stream] = corte
            return true

        case "voice.light":
            let (muestras, frecuencia) = try await VozLigera.shared.decir(
                try texto(a["text"], max: 1500), carpeta: try Descargas.carpeta(try texto(a["id"])),
                velocidad: Float(a["speed"] as? Double ?? 1))
            var pcm = muestras.map { Int16(max(-1, min(1, $0)) * 32767) }
            let data = Data(bytes: &pcm, count: pcm.count * 2)
            return ["pcm": data.base64EncodedString(), "rate": frecuencia]

        case "vad.load":
            let carpeta = try Descargas.carpeta(try texto(a["id"]))
            try await DetectorSilero.shared.cargar(carpeta.appendingPathComponent(try texto(a["file"])))
            return true
        case "vad.frame":
            return try await DetectorSilero.shared.trama(try pcm16(a["pcm"]))
        case "vad.reset":
            await DetectorSilero.shared.reiniciar()
            return true
        default:
            throw BridgeError("Orden desconocida: \(cmd)")
        }
    }

    /// Lo que la app puede hacer aquí (y la memoria libre, para elegir modelos que quepan).
    static func capacidades() -> [String: Any] {
        #if targetEnvironment(simulator)
        let simulador = true
        #else
        let simulador = false
        #endif
        var libre: Int = 0
        #if os(iOS)
        libre = Int(os_proc_available_memory())
        #endif
        return ["LIGHT_VOICE": true, "LOCAL_EAR": true, "LOCAL_BRAIN": !simulador, "SILERO": true,
                "simulator": simulador, "memory_available": libre,
                "memory_total": Int(ProcessInfo.processInfo.physicalMemory)]
    }

    private func liberar(_ id: String) async {
        let ruta = (try? Descargas.carpeta(id).path) ?? ""
        if await Cerebro.shared.cargado == ruta { await Cerebro.shared.descargar() }
        if await Oido.shared.cargado == ruta { await Oido.shared.descargar() }
        await VozLigera.shared.descargar()
    }

    private func texto(_ v: Any?, max: Int = 200) throws -> String {
        guard let s = v as? String, !s.isEmpty, s.count <= max else { throw BridgeError("Dato no válido") }
        return s
    }

    private func archivos(_ v: Any?) throws -> [Descargas.Archivo] {
        guard let lista = v as? [[String: Any]] else { throw BridgeError("Falta la lista de archivos") }
        return try lista.map { f in
            guard let u = f["url"] as? String, let url = URL(string: u), let ruta = f["path"] as? String,
                  !ruta.contains(".."), !ruta.hasPrefix("/") else { throw BridgeError("Archivo no válido") }
            return Descargas.Archivo(url: url, ruta: ruta, tamano: Int64(f["size"] as? Double ?? Double(f["size"] as? Int ?? 0)))
        }
    }

    private func pcm16(_ v: Any?) throws -> [Int16] {
        guard let s = v as? String, let data = Data(base64Encoded: s) else { throw BridgeError("Audio no válido") }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
    }
}

/// Marca de corte compartida con el bucle de generación (que corre fuera del hilo principal).
final class Corte: @unchecked Sendable {
    private let lock = NSLock()
    private var valor = false
    var hecho: Bool { lock.lock(); defer { lock.unlock() }; return valor }
    func cortar() { lock.lock(); valor = true; lock.unlock() }
}
