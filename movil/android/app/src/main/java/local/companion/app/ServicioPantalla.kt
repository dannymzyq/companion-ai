package local.companion.app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Base64
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Servicio de primer plano de la pantalla compartida (Android lo exige para MediaProjection). Lee la pantalla a
 * 1280 px como mucho y, cada ~0,8 s, manda un JPEG a la página. Nada sale del teléfono desde aquí: la imagen va a
 * la conversación igual que la de la cámara. Con el micrófono ya permitido, el servicio también lo declara, para
 * que la conversación siga oyendo con la app en segundo plano.
 */
class ServicioPantalla : Service() {
    companion object {
        var alCuadro: ((String) -> Unit)? = null
        var alTerminar: (() -> Unit)? = null
        private const val CANAL = "pantalla"
    }

    private var proyeccion: MediaProjection? = null
    private var pantalla: VirtualDisplay? = null
    private var lector: ImageReader? = null
    private val hilo = HandlerThread("pantalla").apply { start() }
    private val h = Handler(hilo.looper)
    private var ultima = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL, "Pantalla compartida", NotificationManager.IMPORTANCE_LOW))
        val abrir = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val aviso = Notification.Builder(this, CANAL)
            .setContentTitle("Compartiendo tu pantalla")
            .setContentText("Companion ve lo que tú ves. Vuelve a la app para dejarlo.")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentIntent(abrir).setOngoing(true).build()
        var tipo = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            tipo = tipo or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        }
        startForeground(1, aviso, tipo)

        val code = intent?.getIntExtra("code", 0) ?: 0
        @Suppress("DEPRECATION")
        val data: Intent? = if (Build.VERSION.SDK_INT >= 33) intent?.getParcelableExtra("data", Intent::class.java) else intent?.getParcelableExtra("data")
        if (data == null) { stopSelf(); return START_NOT_STICKY }
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val p = mpm.getMediaProjection(code, data) ?: run { stopSelf(); return START_NOT_STICKY }
        proyeccion = p
        p.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopSelf() }
        }, h)

        val m = resources.displayMetrics
        val escala = minOf(1f, 1280f / max(m.widthPixels, m.heightPixels))
        val w = (m.widthPixels * escala).roundToInt() and 1.inv()
        val hgt = (m.heightPixels * escala).roundToInt() and 1.inv()
        val r = ImageReader.newInstance(w, hgt, PixelFormat.RGBA_8888, 2)
        lector = r
        r.setOnImageAvailableListener({ reader ->
            val img = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
            img.use {
                val ahora = System.currentTimeMillis()
                if (ahora - ultima < 800) return@use
                ultima = ahora
                val plano = it.planes[0]
                val anchoFila = plano.rowStride / plano.pixelStride
                val bmp = Bitmap.createBitmap(anchoFila, hgt, Bitmap.Config.ARGB_8888)
                bmp.copyPixelsFromBuffer(plano.buffer)
                val recorte = if (anchoFila != w) Bitmap.createBitmap(bmp, 0, 0, w, hgt) else bmp
                val out = ByteArrayOutputStream()
                recorte.compress(Bitmap.CompressFormat.JPEG, 60, out)
                if (recorte !== bmp) recorte.recycle()
                bmp.recycle()
                alCuadro?.invoke(Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
            }
        }, h)
        pantalla = p.createVirtualDisplay("companion-pantalla", w, hgt, m.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, h)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        pantalla?.release(); pantalla = null
        lector?.close(); lector = null
        proyeccion?.stop(); proyeccion = null
        hilo.quitSafely()
        alTerminar?.invoke()
        super.onDestroy()
    }
}
