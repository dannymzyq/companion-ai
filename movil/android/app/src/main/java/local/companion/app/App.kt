package local.companion.app

import android.app.Application
import android.webkit.WebSettings

/**
 * Carga el motor de WebView al arrancar la app, antes que la pantalla: así su primera carga (que añade sus recursos
 * a la app) no coincide con la creación de MainActivity.
 */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        try { WebSettings.getDefaultUserAgent(this) } catch (_: Exception) { }
    }
}
