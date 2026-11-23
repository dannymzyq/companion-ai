import Foundation

/// Descarga de los modelos del modo teléfono (oído, cerebro, voz ligera, detector de voz) a
/// Application Support/companion/modelos/<id>/. La lista de archivos con sus tamaños la da el núcleo (JS), que
/// así puede avisar del tamaño antes de bajar. Por archivo: si ya está completo se salta; si se canceló a medias,
/// se reanuda con Range. Solo con wifi salvo que se permita lo contrario.
@MainActor
final class Descargas {
    static let shared = Descargas()
    static let raiz: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("companion/modelos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var v = URLResourceValues()
        v.isExcludedFromBackup = true                 // varios GB: no van a la copia de iCloud
        var d = dir
        try? d.setResourceValues(v)
        return dir
    }()

    struct Archivo { let url: URL; let ruta: String; let tamano: Int64 }

    private var tareas: [String: Task<Void, Never>] = [:]

    static func carpeta(_ id: String) throws -> URL {
        guard id.range(of: "^[A-Za-z0-9._-]{1,80}$", options: .regularExpression) != nil else {
            throw BridgeError("Nombre de modelo no válido")
        }
        return raiz.appendingPathComponent(id, isDirectory: true)
    }

    /// Bytes ya presentes de esa lista (para el estado: completo, a medias o nada).
    static func presentes(_ id: String, _ archivos: [Archivo]) -> Int64 {
        guard let dir = try? carpeta(id) else { return 0 }
        return archivos.reduce(0) { suma, a in
            let attrs = try? FileManager.default.attributesOfItem(atPath: dir.appendingPathComponent(a.ruta).path)
            let tiene = (attrs?[.size] as? Int64) ?? 0
            return suma + (a.tamano > 0 ? min(a.tamano, tiene) : tiene)
        }
    }

    func bajar(_ id: String, _ archivos: [Archivo], conDatosMoviles: Bool,
               progreso: @escaping @MainActor (Int64, Int64) -> Void,
               fin: @escaping @MainActor (String?) -> Void) throws {
        let dir = try Self.carpeta(id)
        if tareas[id] != nil { throw BridgeError("Ya se está descargando") }
        let total = archivos.reduce(0) { $0 + $1.tamano }
        let config = URLSessionConfiguration.default
        config.allowsCellularAccess = conDatosMoviles
        config.allowsExpensiveNetworkAccess = conDatosMoviles
        config.allowsConstrainedNetworkAccess = conDatosMoviles
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 60
        tareas[id] = Task { @MainActor in
            defer { self.tareas[id] = nil }
            var hechos = Self.presentes(id, archivos)
            progreso(hechos, total)
            do {
                for a in archivos {
                    let destino = dir.appendingPathComponent(a.ruta)
                    // Nada fuera de la carpeta del modelo.
                    guard destino.standardizedFileURL.path.hasPrefix(dir.standardizedFileURL.path + "/"),
                          a.url.scheme == "https" else { throw BridgeError("Archivo no válido") }
                    try FileManager.default.createDirectory(at: destino.deletingLastPathComponent(), withIntermediateDirectories: true)
                    let ya = ((try? FileManager.default.attributesOfItem(atPath: destino.path))?[.size] as? Int64) ?? 0
                    if (a.tamano > 0 && ya >= a.tamano) || (a.tamano == 0 && ya > 0) { continue }
                    var req = URLRequest(url: a.url)
                    if ya > 0 { req.setValue("bytes=\(ya)-", forHTTPHeaderField: "Range") }
                    let base = hechos
                    let escrito = try await Trozos.bajar(req, a: destino, sesion: config, desde: ya) { n in
                        progreso(base + n, total)
                    }
                    hechos = base + escrito
                    progreso(hechos, total)
                }
                fin(nil)
            } catch is CancellationError {
                fin("cancelada")
            } catch {
                let e = error as NSError
                fin(e.domain == NSURLErrorDomain && e.code == NSURLErrorNotConnectedToInternet
                    ? (conDatosMoviles ? "sin conexión" : "sin wifi") : ((error as? BridgeError)?.message ?? "falló (\(e.code))"))
            }
        }
    }

    func cancelar(_ id: String) { tareas[id]?.cancel() }

    func borrar(_ id: String) throws {
        cancelar(id)
        try? FileManager.default.removeItem(at: try Self.carpeta(id))
    }
}

/// Un archivo por trozos (delegado de datos): se escriben según llegan, sin pasar byte a byte. Si el servidor
/// ignora el Range (200) se empieza el archivo de cero.
final class Trozos: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let destino: URL
    private var handle: FileHandle?
    private var escrito: Int64 = 0
    private var ultimoAviso = Date.distantPast
    private let avisar: @MainActor (Int64) -> Void
    private var cont: CheckedContinuation<Int64, Error>?
    private let desde: Int64

    private init(destino: URL, desde: Int64, avisar: @escaping @MainActor (Int64) -> Void) {
        self.destino = destino; self.desde = desde; self.avisar = avisar
    }

    static func bajar(_ req: URLRequest, a destino: URL, sesion config: URLSessionConfiguration, desde: Int64,
                      avisar: @escaping @MainActor (Int64) -> Void) async throws -> Int64 {
        let t = Trozos(destino: destino, desde: desde, avisar: avisar)
        let session = URLSession(configuration: config, delegate: t, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let task = session.dataTask(with: req)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { c in t.cont = c; task.resume() }
        } onCancel: { task.cancel() }
    }

    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 || status == 206 else {
            cont?.resume(throwing: BridgeError("El servidor respondió \(status)")); cont = nil
            completionHandler(.cancel); return
        }
        if status == 200 || !FileManager.default.fileExists(atPath: destino.path) {
            FileManager.default.createFile(atPath: destino.path, contents: nil)   // de cero
            escrito = -desde                                                         // lo que ya había no cuenta
            if !FileManager.default.fileExists(atPath: destino.path) { escrito = 0 }
        }
        handle = try? FileHandle(forWritingTo: destino)
        _ = try? handle?.seekToEnd()
        completionHandler(handle == nil ? .cancel : .allow)
    }

    func urlSession(_ s: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        do { try handle?.write(contentsOf: data) } catch { dataTask.cancel(); return }
        escrito += Int64(data.count)
        if Date().timeIntervalSince(ultimoAviso) > 0.4 {
            ultimoAviso = Date()
            let n = escrito
            Task { @MainActor in self.avisar(n) }
        }
    }

    func urlSession(_ s: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        try? handle?.close()
        if let error { cont?.resume(throwing: (error as NSError).code == NSURLErrorCancelled ? CancellationError() : error) }
        else { cont?.resume(returning: escrito) }
        cont = nil
    }
}
