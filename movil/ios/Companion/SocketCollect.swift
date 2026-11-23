import Foundation

/// WebSocket de un solo uso para la voz en la nube: abre `url` con las cabeceras dadas (el WebView no deja poner
/// Origin ni User-Agent), manda los mensajes de texto y junta la carga de los mensajes binarios hasta que llega un
/// texto con «Path:<endPath>». El protocolo (ficha, SSML) lo arma el núcleo en JS; aquí solo hay transporte.
enum SocketCollect {
    struct Failure: Error { let message: String; let serverDate: String? }

    static func run(url: URL, headers: [String: String], messages: [String], endPath: String,
                    timeout: TimeInterval = 20) async throws -> Data {
        var req = URLRequest(url: url, timeoutInterval: timeout)
        for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }
        let task = URLSession.shared.webSocketTask(with: req)
        task.resume()
        defer { task.cancel(with: .normalClosure, reason: nil) }
        do {
            for m in messages { try await task.send(.string(m)) }
            var audio = Data()
            let deadline = Date().addingTimeInterval(timeout)
            while Date() < deadline {
                switch try await task.receive() {
                case .string(let text):
                    if text.contains("Path:\(endPath)") { return audio }
                case .data(let data):
                    // Dos bytes con el largo de la cabecera (big-endian), la cabecera y después el audio.
                    guard data.count >= 2 else { continue }
                    let headerLen = Int(data[data.startIndex]) << 8 | Int(data[data.startIndex + 1])
                    let start = data.startIndex + 2 + headerLen
                    if start < data.endIndex { audio.append(data[start...]) }
                @unknown default:
                    continue
                }
            }
            throw Failure(message: "La voz en la nube tardó demasiado", serverDate: nil)
        } catch let f as Failure {
            throw f
        } catch {
            // Un 403 al conectar suele ser el reloj desfasado: se devuelve la hora del servidor para corregir la ficha.
            let date = (task.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Date")
            let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
            throw Failure(message: "La voz en la nube no respondió (\(status == 0 ? (error as NSError).code : status))", serverDate: date)
        }
    }
}
