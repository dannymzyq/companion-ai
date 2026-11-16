import Foundation
import SherpaOnnx

/// Voz ligera dentro del teléfono: las voces Piper de voices.json («light») con sherpa-onnx (1.13, que aún trae
/// espeak-ng). Cada voz es una carpeta con <modelo>.onnx, tokens.txt y espeak-ng-data (formato vits-piper de
/// sherpa-onnx). El cambio de tono (como tts_light.py) lo hace el núcleo en JS al pasar a 24 kHz.
actor VozLigera {
    static let shared = VozLigera()

    private var tts: [String: SherpaOnnxOfflineTtsWrapper] = [:]

    private func motor(_ carpeta: URL) throws -> SherpaOnnxOfflineTtsWrapper {
        if let t = tts[carpeta.path] { return t }
        let archivos = (try? FileManager.default.contentsOfDirectory(atPath: carpeta.path)) ?? []
        guard let onnx = archivos.first(where: { $0.hasSuffix(".onnx") }) else {
            throw MotorError("Falta el modelo de la voz ligera")
        }
        let vits = sherpaOnnxOfflineTtsVitsModelConfig(
            model: carpeta.appendingPathComponent(onnx).path,
            tokens: carpeta.appendingPathComponent("tokens.txt").path,
            dataDir: carpeta.appendingPathComponent("espeak-ng-data").path)
        let modelo = sherpaOnnxOfflineTtsModelConfig(vits: vits, numThreads: 2, debug: 0, provider: "cpu")
        var config = sherpaOnnxOfflineTtsConfig(model: modelo)
        let t = SherpaOnnxOfflineTtsWrapper(config: &config)
        tts[carpeta.path] = t
        return t
    }

    /// Devuelve las muestras (float, −1…1) y su frecuencia (22 050 Hz en las voces Piper).
    func decir(_ texto: String, carpeta: URL, velocidad: Float) throws -> (muestras: [Float], frecuencia: Int) {
        let audio = try motor(carpeta).generate(text: texto, sid: 0, speed: velocidad)
        return (audio.samples, Int(audio.sampleRate))
    }

    func descargar() { tts = [:] }
}

/// Detector de voz Silero (sherpa-onnx). sherpa-onnx no da la probabilidad por trama, solo si ahora hay voz: el
/// núcleo lo usa como 0/1 con el mismo corte de turnos (y, si esto falla, con su detector por energía).
actor DetectorSilero {
    static let shared = DetectorSilero()

    private var vad: SherpaOnnxVoiceActivityDetectorWrapper?

    func cargar(_ modelo: URL) throws {
        if vad != nil { return }
        let silero = sherpaOnnxSileroVadModelConfig(model: modelo.path, threshold: 0.5, minSilenceDuration: 0.1,
                                                    minSpeechDuration: 0.06, windowSize: 512, maxSpeechDuration: 30)
        var config = sherpaOnnxVadModelConfig(sileroVad: silero, sampleRate: 16000, numThreads: 1, provider: "cpu", debug: 0)
        vad = SherpaOnnxVoiceActivityDetectorWrapper(config: &config, buffer_size_in_seconds: 5)
    }

    /// Una trama de 512 muestras a 16 kHz → ¿hay voz ahora?
    func trama(_ pcm: [Int16]) throws -> Bool {
        guard let vad else { throw MotorError("Silero no está cargado") }
        vad.acceptWaveform(samples: pcm.map { Float($0) / 32768 })
        while !vad.isEmpty() { vad.pop() }       // los tramos los corta el núcleo; aquí no se guardan
        return vad.isSpeechDetected()
    }

    func reiniciar() { vad?.reset() }
}
