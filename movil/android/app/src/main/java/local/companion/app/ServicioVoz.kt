package local.companion.app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.content.ContextCompat

/**
 * Servicio de primer plano de micrófono para llamadas en vivo (Android 11+ corta el micrófono tras ~1 min fuera de la
 * app o en PiP si no hay un servicio foreground de tipo microphone activo).
 */
class ServicioVoz : Service() {
    companion object {
        private const val CANAL = "companion_voz"
        private const val NOTIF_ID = 2

        fun iniciar(ctx: Context) {
            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
            try {
                ContextCompat.startForegroundService(ctx, Intent(ctx, ServicioVoz::class.java))
            } catch (_: Exception) {}
        }

        fun parar(ctx: Context) {
            try {
                ctx.stopService(Intent(ctx, ServicioVoz::class.java))
            } catch (_: Exception) {}
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL, "Conversación por voz", NotificationManager.IMPORTANCE_LOW))
        val abrir = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val aviso = Notification.Builder(this, CANAL)
            .setContentTitle("Conversación activa")
            .setContentText("Companion sigue escuchándote en segundo plano.")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(abrir)
            .setOngoing(true)
            .build()
        try {
            startForeground(NOTIF_ID, aviso, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } catch (_: Exception) {
            stopSelf()
        }
        return START_NOT_STICKY
    }
}
