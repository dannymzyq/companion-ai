import SwiftUI
import WebKit

/// La interfaz de web/ (la misma que en la PC) dentro de un WKWebView. Los archivos salen del paquete de la app
/// por app://companion/ (AppScheme) y movil/core/boot.js sustituye al servidor de la PC antes de que cargue.
struct CompanionView: UIViewRepresentable {
    func makeCoordinator() -> Bridge { Bridge() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(AppScheme(), forURLScheme: AppScheme.scheme)
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let content = config.userContentController
        content.addScriptMessageHandler(context.coordinator, contentWorld: .page, name: "native")
        if let url = AppScheme.root?.appendingPathComponent("core/boot.js"),
           let boot = try? String(contentsOf: url, encoding: .utf8) {
            content.addUserScript(WKUserScript(source: boot, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }

        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = .black
        web.scrollView.isScrollEnabled = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsBackForwardNavigationGestures = false
        #if DEBUG
        web.isInspectable = true            // Safari › Desarrollo › Simulador para ver la consola
        context.coordinator.testHook = TestHook(webView: web)
        #endif
        context.coordinator.webView = web
        web.uiDelegate = context.coordinator
        web.load(URLRequest(url: URL(string: "\(AppScheme.scheme)://companion/index.html")!))
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
