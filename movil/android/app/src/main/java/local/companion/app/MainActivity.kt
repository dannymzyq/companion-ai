package local.companion.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.PictureInPictureParams
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.util.Rational
import android.view.View
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import java.io.File

/**
 * La interfaz de web/ (la misma que en la PC y en iOS) en un WebView. Los archivos salen de assets/www por
 * https://appassets.androidplatform.net (WebViewAssetLoader) y movil/core/boot.js sustituye al servidor de la PC
 * antes de que cargue la página. Puente: Bridge.kt (los mismos comandos que Bridge.swift en iOS).
 */
class MainActivity : ComponentActivity() {
    companion object {
        const val ORIGEN = "https://appassets.androidplatform.net"
    }

    lateinit var web: WebView
    lateinit var bridge: Bridge
    private var permisoPendiente: PermissionRequest? = null
    var flotanteArmada = false
        set(v) { field = v; aplicarFlotante() }

    private val pedirPermisos = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { r ->
        val p = permisoPendiente ?: return@registerForActivityResult
        permisoPendiente = null
        val dados = p.resources.filter { recurso ->
            when (recurso) {
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> r[Manifest.permission.RECORD_AUDIO] ?: tiene(Manifest.permission.RECORD_AUDIO)
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> r[Manifest.permission.CAMERA] ?: tiene(Manifest.permission.CAMERA)
                else -> false
            }
        }
        if (dados.isEmpty()) p.deny() else p.grant(dados.toTypedArray())
    }

    // Elegir un archivo (VRM propio) desde la página: Android solo abre el selector si la app lo hace.
    private var archivoPendiente: android.webkit.ValueCallback<Array<android.net.Uri>>? = null
    private val elegirArchivo = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        archivoPendiente?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
        archivoPendiente = null
    }

    val pedirPantalla = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        bridge.pantallaPermitida(r.resultCode, r.data)
    }

    fun tiene(permiso: String) = ContextCompat.checkSelfPermission(this, permiso) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        android.util.Log.i(Bridge.TAG, "MainActivity creada")
        WindowCompat.setDecorFitsSystemWindows(window, false)     // la página dibuja bajo las barras (como en iOS)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)   // consola por adb solo en la de depuración
        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#0C0B14"))
        setContentView(web)
        bridge = Bridge(this)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            allowContentAccess = false
            setSupportZoom(false)          // sin zoom de la página: solo el personaje se acerca
            builtInZoomControls = false
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = false
            textZoom = 100
        }
        web.isVerticalScrollBarEnabled = false
        web.overScrollMode = View.OVER_SCROLL_NEVER

        // Archivos: www del paquete y los VRM propios (/propios/<id>.vrm, en la carpeta de la app).
        val loader = WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .addPathHandler("/propios/", Propios(Bridge.carpetaVrm(this)))
            .addPathHandler("/", WebViewAssetLoader.AssetsPathHandler(this).let { assets ->
                WebViewAssetLoader.PathHandler { path -> assets.handle("www/" + path.ifEmpty { "index.html" }) }
            })
            .build()
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                if (request.url.host == "appassets.androidplatform.net") loader.shouldInterceptRequest(request.url)?.also {
                    it.responseHeaders = (it.responseHeaders ?: emptyMap()) + mapOf("Cache-Control" to "no-cache")
                } else null
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Enlaces de fuera (conseguir una clave…): al navegador, nunca dentro de la app.
                if (request.url.host == "appassets.androidplatform.net") return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            // Micrófono y cámara para la propia interfaz: el permiso de Android se pide aquí la primera vez.
            override fun onPermissionRequest(request: PermissionRequest) {
                if (request.origin.toString().trimEnd('/') != ORIGEN) { request.deny(); return }
                val falta = request.resources.mapNotNull {
                    when (it) {
                        PermissionRequest.RESOURCE_AUDIO_CAPTURE -> Manifest.permission.RECORD_AUDIO
                        PermissionRequest.RESOURCE_VIDEO_CAPTURE -> Manifest.permission.CAMERA
                        else -> null
                    }
                }.filterNot { tiene(it) }
                if (falta.isEmpty()) { request.grant(request.resources); return }
                permisoPendiente = request
                pedirPermisos.launch(falta.toTypedArray())
            }

            override fun onShowFileChooser(view: WebView, callback: android.webkit.ValueCallback<Array<android.net.Uri>>,
                                           params: FileChooserParams): Boolean {
                archivoPendiente?.onReceiveValue(null)
                archivoPendiente = callback
                // «.vrm» no tiene tipo MIME conocido en Android: se deja elegir cualquier archivo y la página lo valida.
                val i = Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                return try { elegirArchivo.launch(Intent.createChooser(i, "Elegir un archivo")); true }
                catch (e: Exception) { archivoPendiente = null; false }
            }
        }

        // Puente y boot.js antes que nada de la página (como WKUserScript al empezar el documento en iOS).
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER) ||
            !WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            web.loadData("<p style='color:#fff;font:16px sans-serif;padding:24px'>Actualiza «Android System WebView» desde Play Store para usar Companion.</p>", "text/html", "utf-8")
            return
        }
        WebViewCompat.addWebMessageListener(web, "companionPuente", setOf(ORIGEN), bridge)
        WebViewCompat.addDocumentStartJavaScript(web, Bridge.SHIM, setOf(ORIGEN))
        val boot = assets.open("www/core/boot.js").bufferedReader().readText()
        WebViewCompat.addDocumentStartJavaScript(web, boot, setOf(ORIGEN))

        vigilarTeclado()
        vigilarAudio()
        web.loadUrl("$ORIGEN/index.html")
    }

    /** El teclado se pone ENCIMA (adjustNothing): solo la barra de abajo sube lo que ocupa (--teclado, ui_movil.js). */
    private fun vigilarTeclado() {
        ViewCompat.setOnApplyWindowInsetsListener(web) { v, insets ->
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            val nav = insets.getInsets(WindowInsetsCompat.Type.navigationBars()).bottom
            val alto = if (ime > 0) (ime / resources.displayMetrics.density).toInt() else 0
            web.evaluateJavascript("window.__teclado && window.__teclado($alto, 0.25)", null)
            // Márgenes seguros de Android para env(safe-area-inset-*): WebView no los da con la página a pantalla completa.
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val d = resources.displayMetrics.density
            web.evaluateJavascript(
                // Antes de que cargue la página no hay documentElement (daba «null.style» al arrancar).
                "(()=>{const e=document.documentElement;if(!e)return;" +
                "e.style.setProperty('--sat','${(bars.top / d).toInt()}px');" +
                "e.style.setProperty('--sab','${(nav / d).toInt()}px')})()", null)
            ViewCompat.onApplyWindowInsets(v, insets)
        }
    }

    /** Auriculares que se conectan o se quitan: la página reabre el micrófono predeterminado (como en iOS). */
    private var audioCallback: AudioDeviceCallback? = null

    private fun vigilarAudio() {
        val am = getSystemService(AUDIO_SERVICE) as AudioManager
        val cb = object : AudioDeviceCallback() {
            override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = bridge.emitir("audioRoute", "true")
            override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = bridge.emitir("audioRoute", "true")
        }
        audioCallback = cb
        am.registerAudioDeviceCallback(cb, null)
    }

    // ---------------------------------------------------------------- ventana flotante (picture in picture)
    // En Android la ventanita es la propia app en pequeño (el WebView sigue dibujando en directo): no hace falta
    // mandar cuadros como en iOS. Con la ventana encendida, se abre sola al salir de la app (Android 12+) o al
    // pulsar inicio (onUserLeaveHint, Android 10-11).
    private fun parametros(): PictureInPictureParams = PictureInPictureParams.Builder()
        .setAspectRatio(Rational(9, 16))
        .apply { if (Build.VERSION.SDK_INT >= 31) setAutoEnterEnabled(flotanteArmada).setSeamlessResizeEnabled(true) }
        .build()

    private fun aplicarFlotante() {
        if (packageManager.hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)) setPictureInPictureParams(parametros())
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (flotanteArmada && Build.VERSION.SDK_INT < 31 && !isInPictureInPictureMode) enterPictureInPictureMode(parametros())
    }

    override fun onPictureInPictureModeChanged(enPip: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(enPip, newConfig)
        bridge.emitir("pipModo", enPip.toString())
        if (!enPip) bridge.emitir("pip", "false")
    }

    // La página sigue viva fuera de la app (conversación, ventana flotante, pantalla compartida): no se pausan sus
    // temporizadores al salir.
    override fun onPause() { super.onPause() }

    @Deprecated("Atrás deja la app en segundo plano sin cerrarla (la conversación sigue)")
    override fun onBackPressed() {
        web.evaluateJavascript("(()=>{const s=document.getElementById('settings');if(s&&!s.hidden){document.getElementById('close-settings').click();return 1}return 0})()") {
            if (it != "1") moveTaskToBack(true)
        }
    }

    override fun onDestroy() {
        android.util.Log.i(Bridge.TAG, "MainActivity cerrada")
        audioCallback?.let {
            (getSystemService(AUDIO_SERVICE) as? AudioManager)?.unregisterAudioDeviceCallback(it)
            audioCallback = null
        }
        bridge.cerrarTodo()
        // Sin esto, la página vieja seguiría corriendo (otra conversación, otro micrófono) hasta que la limpie el GC.
        (web.parent as? android.view.ViewGroup)?.removeView(web)
        web.destroy()
        super.onDestroy()
    }

    fun pedirCapturaPantalla() {
        val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        pedirPantalla.launch(mpm.createScreenCaptureIntent())
    }
}

/** Los VRM propios del usuario (carpeta de la app), en /propios/<id>.vrm. */
private class Propios(private val dir: File) : WebViewAssetLoader.PathHandler {
    override fun handle(path: String): WebResourceResponse? {
        if (!Regex("^[a-z0-9_-]{1,60}\\.vrm$").matches(path)) return null
        val f = File(dir, path)
        if (!f.isFile) return null
        return WebResourceResponse("application/octet-stream", null, f.inputStream())
    }
}
