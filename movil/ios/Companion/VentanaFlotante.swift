import AVFoundation
import AVKit
import UIKit

/// Ventana flotante (picture in picture) con el personaje, como las apps de videollamada: la página manda cada
/// cuadro (JPEG del dibujo 3D, ui_movil.js) y aquí se pone en una capa de vídeo que iOS saca a una ventanita encima
/// de las demás apps. WebKit no deja hacer picture in picture de un lienzo, por eso va en nativo.
@MainActor
final class VentanaFlotante: NSObject, AVPictureInPictureControllerDelegate, AVPictureInPictureSampleBufferPlaybackDelegate {
    private let capa = AVSampleBufferDisplayLayer()
    private let vista = UIView(frame: CGRect(x: 0, y: 0, width: 4, height: 4))
    private var pip: AVPictureInPictureController?
    private var formato: CMVideoFormatDescription?
    var alCerrar: (() -> Void)?

    static var disponible: Bool { AVPictureInPictureController.isPictureInPictureSupported() }

    func abrir(en padre: UIView, ancho: Int, alto: Int) throws {
        guard Self.disponible else { throw BridgeError("Este iPhone no admite ventanas flotantes") }
        if vista.superview == nil {
            // La capa tiene que estar en pantalla (casi invisible) para que iOS la pueda sacar a la ventanita.
            vista.frame = CGRect(x: 0, y: 0, width: CGFloat(ancho) / 20, height: CGFloat(alto) / 20)
            vista.alpha = 0.01
            vista.isUserInteractionEnabled = false
            capa.frame = vista.bounds
            capa.videoGravity = .resizeAspect
            vista.layer.addSublayer(capa)
            padre.addSubview(vista)
        }
        if pip == nil {
            let fuente = AVPictureInPictureController.ContentSource(sampleBufferDisplayLayer: capa, playbackDelegate: self)
            let c = AVPictureInPictureController(contentSource: fuente)
            c.delegate = self
            c.requiresLinearPlayback = true             // sin botones de adelantar/atrasar
            c.canStartPictureInPictureAutomaticallyFromInline = true   // al salir de la app, se abre sola
            pip = c
        }
        // iOS necesita una sesión de audio de reproducción para abrir la ventana. Si ya está en «playAndRecord»
        // (micrófono abierto por la página) no se toca: cambiarla interrumpe la voz de la página.
        let s = AVAudioSession.sharedInstance()
        if s.category != .playAndRecord && s.category != .playback {
            try? s.setCategory(.playback, mode: .default, options: [.mixWithOthers])
        }
        try? s.setActive(true)
    }

    /// Un cuadro nuevo de la página (JPEG). Se guarda en un bucle con los últimos segundos: con la app en segundo
    /// plano iOS duerme la página (WebKit) y deja de mandar cuadros, y entonces la ventana repite ese bucle (de ida y
    /// vuelta, para que no salte) y el personaje sigue moviéndose. Si la página vuelve a mandar, manda ella.
    func cuadro(_ jpeg: Data) {
        ultimo = Date()
        bucle.append(jpeg)
        if bucle.count > Self.largo { bucle.removeFirst(bucle.count - Self.largo) }
        mostrar(jpeg)
        if reloj == nil {
            reloj = Timer.scheduledTimer(withTimeInterval: 1.0 / 15, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.repetir() }
            }
        }
    }
    private static let largo = 60                  // 4 s a 15 cuadros por segundo
    private var bucle: [Data] = []
    private var ultimo = Date.distantPast
    private var reloj: Timer?
    private var paso = 0, sentido = 1

    private func repetir() {
        guard Date().timeIntervalSince(ultimo) > 0.35, bucle.count > 2 else { paso = bucle.count - 1; sentido = -1; return }
        paso += sentido
        if paso >= bucle.count - 1 { paso = bucle.count - 1; sentido = -1 }
        if paso <= 0 { paso = 0; sentido = 1 }
        mostrar(bucle[paso], repetido: true)
    }

    private func mostrar(_ jpeg: Data, repetido: Bool = false) {
        guard let img = UIImage(data: jpeg)?.cgImage, let buf = Self.pixelBuffer(img) else { return }
        if formato == nil || CMVideoFormatDescriptionGetDimensions(formato!).width != Int32(img.width) {
            CMVideoFormatDescriptionCreateForImageBuffer(allocator: nil, imageBuffer: buf, formatDescriptionOut: &formato)
        }
        guard let formato else { return }
        var tiempo = CMSampleTimingInfo(duration: .invalid, presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
                                        decodeTimeStamp: .invalid)
        var muestra: CMSampleBuffer?
        CMSampleBufferCreateReadyWithImageBuffer(allocator: nil, imageBuffer: buf, formatDescription: formato,
                                                 sampleTiming: &tiempo, sampleBufferOut: &muestra)
        guard let muestra else { return }
        if let adj = CMSampleBufferGetSampleAttachmentsArray(muestra, createIfNecessary: true), CFArrayGetCount(adj) > 0 {
            let d = unsafeBitCast(CFArrayGetValueAtIndex(adj, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(d, Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                                 Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        if capa.status == .failed { capa.flush() }
        capa.enqueue(muestra)
        #if PRUEBAS
        if repetido { repetidos += 1 } else { cuenta += 1 }
        if Date().timeIntervalSince(desde) >= 5 {
            let fondo = UIApplication.shared.applicationState == .background ? "en segundo plano" : "delante"
            Registro.anotar("Ventana flotante: \(cuenta) cuadros en 5 s (+\(repetidos) del bucle), app \(fondo), ventana \(activa ? "abierta" : "cerrada")")
            cuenta = 0; repetidos = 0; desde = Date()
        }
        #endif
        if let pip, !pip.isPictureInPictureActive, pip.isPictureInPicturePossible, empezar {
            empezar = false
            pip.startPictureInPicture()
        }
    }
    var empezar = false
    private var cuenta = 0, repetidos = 0
    private var desde = Date()

    func cerrar() {
        empezar = false
        reloj?.invalidate(); reloj = nil; bucle.removeAll()
        pip?.stopPictureInPicture()
    }

    var activa: Bool { pip?.isPictureInPictureActive ?? false }

    private static func pixelBuffer(_ img: CGImage) -> CVPixelBuffer? {
        var buf: CVPixelBuffer?
        let attrs = [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true,
                     kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary
        CVPixelBufferCreate(nil, img.width, img.height, kCVPixelFormatType_32BGRA, attrs, &buf)
        guard let buf else { return nil }
        CVPixelBufferLockBaseAddress(buf, [])
        defer { CVPixelBufferUnlockBaseAddress(buf, []) }
        guard let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: img.width, height: img.height, bitsPerComponent: 8,
                                  bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { return nil }
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: img.width, height: img.height))
        return buf
    }

    // MARK: AVPictureInPictureControllerDelegate
    nonisolated func pictureInPictureControllerDidStopPictureInPicture(_ c: AVPictureInPictureController) {
        Task { @MainActor in self.alCerrar?() }
    }
    nonisolated func pictureInPictureController(_ c: AVPictureInPictureController, failedToStartPictureInPictureWithError error: Error) {
        Task { @MainActor in
            webLog.log("Ventana flotante: \(error.localizedDescription, privacy: .public)")
            #if PRUEBAS
            Registro.anotar("Ventana flotante no se abrió: \((error as NSError).domain) \((error as NSError).code) \(error.localizedDescription)")
            #endif
            self.alCerrar?()
        }
    }

    // MARK: AVPictureInPictureSampleBufferPlaybackDelegate (en directo: sin pausa ni duración)
    nonisolated func pictureInPictureController(_ c: AVPictureInPictureController, setPlaying playing: Bool) {}
    nonisolated func pictureInPictureControllerTimeRangeForPlayback(_ c: AVPictureInPictureController) -> CMTimeRange {
        CMTimeRange(start: .negativeInfinity, duration: .positiveInfinity)
    }
    nonisolated func pictureInPictureControllerIsPlaybackPaused(_ c: AVPictureInPictureController) -> Bool { false }
    nonisolated func pictureInPictureController(_ c: AVPictureInPictureController, didTransitionToRenderSize newRenderSize: CMVideoDimensions) {}
    nonisolated func pictureInPictureController(_ c: AVPictureInPictureController, skipByInterval skipInterval: CMTime) async {}
}
