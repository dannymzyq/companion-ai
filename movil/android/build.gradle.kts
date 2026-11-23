// App del companion para Android: la misma interfaz (web/) y el mismo núcleo (movil/core) que la de iOS, dentro de
// un WebView. Lo nativo solo hace lo que la página no puede (claves, red sin CORS, ventana flotante, pantalla).
plugins {
    // AGP 9 trae Kotlin incluido (sin el plugin org.jetbrains.kotlin.android).
    id("com.android.application") version "9.5.2" apply false
}
