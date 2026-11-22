package local.companion.app

import android.app.Activity
import android.content.Intent
import androidx.core.content.ContextCompat

/**
 * Compartir pantalla (como en la PC y en iOS): Android pide permiso con su propio diálogo y ServicioPantalla manda
 * una imagen de lo que se ve cada ~0,8 s a la página (`pantalla`), que la pasa a la conversación.
 */
class Pantalla(private val act: MainActivity, private val bridge: Bridge) {
    var activa = false
        private set

    /** true si ya se está compartiendo; si no, abre el diálogo de Android y devuelve false. */
    fun empezar(): Boolean {
        if (activa) return true
        act.pedirCapturaPantalla()
        return false
    }

    fun permitida(code: Int, data: Intent?) {
        if (code != Activity.RESULT_OK || data == null) return       // el usuario dijo que no: nada que hacer
        ServicioPantalla.alCuadro = { b64 -> bridge.emitir("pantalla", "'$b64'") }
        ServicioPantalla.alTerminar = {
            if (activa) { activa = false; bridge.emitir("pantallaEstado", "false") }
        }
        val i = Intent(act, ServicioPantalla::class.java).putExtra("code", code).putExtra("data", data)
        ContextCompat.startForegroundService(act, i)
        activa = true
        bridge.emitir("pantallaEstado", "true")
    }

    fun parar() {
        if (!activa) return
        act.stopService(Intent(act, ServicioPantalla::class.java))
    }
}
