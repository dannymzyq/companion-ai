import Foundation
import WhisperKit

/// Oído dentro del teléfono: Whisper en CoreML (WhisperKit, modelos de argmaxinc/whisperkit-coreml).
/// En el simulador corre en el procesador; en el iPhone usa el Neural Engine.
actor Oido {
    static let shared = Oido()

    private var kit: WhisperKit?
    private(set) var cargado: String?

    func cargar(_ carpeta: URL) async throws -> Double {
        if cargado == carpeta.path, kit != nil { return 0 }
        kit = nil
        let t = Date()
        let config = WhisperKitConfig(modelFolder: carpeta.path, verbose: false, logLevel: .error,
                                      prewarm: true, load: true, download: false)
        kit = try await WhisperKit(config)
        cargado = carpeta.path
        return Date().timeIntervalSince(t)
    }

    func descargar() { kit = nil; cargado = nil }

    /// PCM de 16 bits a 16 kHz → texto en español ('' si no hay habla).
    func transcribir(_ pcm: [Int16], idioma: String = "es") async throws -> String {
        guard let kit else { throw MotorError("El oído del teléfono no está cargado") }
        let audio = pcm.map { Float($0) / 32768 }
        let opciones = DecodingOptions(task: .transcribe, language: idioma, temperature: 0,
                                       skipSpecialTokens: true, withoutTimestamps: true,
                                       suppressBlank: true, noSpeechThreshold: 0.6)
        let resultados = try await kit.transcribe(audioArray: audio, decodeOptions: opciones)
        return resultados.map(\.text).joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
