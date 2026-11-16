import Foundation

// Mide en el Mac los motores del modo teléfono (los mismos archivos de Motores/ que usa la app):
//   probar_motores oido <carpeta whisperkit> <audio.wav 16 kHz>
//   probar_motores cerebro <carpeta mlx> "<pregunta>" [maxTokens]
//   probar_motores voz <carpeta vits-piper> "<texto>"
//   probar_motores vad <silero.onnx> <audio.wav 16 kHz>

func leerWav(_ ruta: String) throws -> [Int16] {
    let d = try Data(contentsOf: URL(fileURLWithPath: ruta))
    var i = 12
    while i + 8 <= d.count {
        let id = String(decoding: d[i..<i + 4], as: UTF8.self)
        let n = Int(d[i + 4]) | Int(d[i + 5]) << 8 | Int(d[i + 6]) << 16 | Int(d[i + 7]) << 24
        if id == "data" {
            return d[(i + 8)..<min(d.count, i + 8 + n)].withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
        }
        i += 8 + n + (n % 2)
    }
    throw MotorError("WAV sin datos")
}

func s(_ x: Double) -> String { String(format: "%.2f s", x) }

let args = CommandLine.arguments
guard args.count >= 4 else { print("uso: probar_motores oido|cerebro|voz|vad …"); exit(2) }
let carpeta = URL(fileURLWithPath: args[2])

do {
    switch args[1] {
    case "oido":
        let pcm = try leerWav(args[3])
        print("carga:", s(try await Oido.shared.cargar(carpeta)))
        for vez in 1...3 {
            let t = Date()
            let texto = try await Oido.shared.transcribir(pcm)
            print("vez \(vez): \(s(Date().timeIntervalSince(t))) para \(s(Double(pcm.count) / 16000)) de audio → \(texto)")
        }
    case "cerebro":
        let max = args.count > 4 ? Int(args[4]) ?? 200 : 200
        print("carga:", s(try await Cerebro.shared.cargar(carpeta)))
        let sistema = "Eres Mika, 25 años, asistente personal. Hablas en voz alta: 1 a 3 frases cortas, sin emojis. "
            + "Empieza cada respuesta con una etiqueta de emoción como [emo:feliz]."
        for vez in 1...2 {
            final class Texto: @unchecked Sendable { var v = "" }
            let out = Texto()
            let m = try await Cerebro.shared.generar([["role": "system", "content": sistema], ["role": "user", "content": args[3]]],
                                                     temperatura: 0.7, topP: 0.92, maxTokens: max) { out.v += $0 }
            print("vez \(vez): primer texto \(s(m.primerTrozo)), \(m.promptTokens) tokens de entrada, \(m.tokens) generados, "
                  + String(format: "%.1f tokens/s", m.tokensPorSegundo))
            print("  → \(out.v.replacingOccurrences(of: "\n", with: " "))")
        }
        print("memoria del proceso:", String(format: "%.2f GB", Double(memoriaResidente()) / 1e9))
    case "voz":
        for vez in 1...2 {
            let t = Date()
            let (m, f) = try await VozLigera.shared.decir(args[3], carpeta: carpeta, velocidad: 1.0)
            print("vez \(vez): \(s(Date().timeIntervalSince(t))) para \(s(Double(m.count) / Double(f))) de audio a \(f) Hz")
            if vez == 2 {
                var pcm = m.map { Int16(max(-1, min(1, $0)) * 32767) }
                let salida = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("voz_ligera.raw")
                try Data(bytes: &pcm, count: pcm.count * 2).write(to: salida)
                print("  audio: \(salida.path)")
            }
        }
    case "vad":
        let pcm = try leerWav(args[3])
        try await DetectorSilero.shared.cargar(carpeta)
        var marcas = ""
        var t = Date()
        for i in stride(from: 0, to: pcm.count - 511, by: 512) {
            marcas += try await DetectorSilero.shared.trama(Array(pcm[i..<i + 512])) ? "█" : "·"
        }
        print("\(marcas.count) tramas de 32 ms en \(s(Date().timeIntervalSince(t)))")
        print(marcas)
        t = Date()
    default:
        print("orden desconocida")
    }
} catch {
    print("ERROR:", error)
    exit(1)
}

func memoriaResidente() -> UInt64 {
    var info = mach_task_basic_info()
    var n = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size) / 4
    let r = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: integer_t.self, capacity: Int(n)) { task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &n) }
    }
    return r == KERN_SUCCESS ? info.resident_size : 0
}
