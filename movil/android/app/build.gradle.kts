plugins {
    id("com.android.application")
}

android {
    namespace = "local.companion.app"
    compileSdk = 37

    defaultConfig {
        applicationId = "local.companion.app"
        minSdk = 29            // Android 10: MediaProjection con servicio y WebView moderno
        targetSdk = 37
        versionCode = 3
        versionName = "0.9.2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Sin tienda: se firma con la clave de depuración para poder instalarla desde el Mac (como en iOS con
            // el Apple ID gratuito). Para publicarla habría que usar una clave propia.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { buildConfig = true }
    androidResources { noCompress += listOf("vrm", "glb", "wav") }
}

dependencies {
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.activity:activity-ktx:1.13.0")
    implementation("androidx.webkit:webkit:1.18.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
}

// La interfaz (web/) y el núcleo (movil/core) se copian a assets/www antes de compilar, con el mismo guion que iOS.
val copiarWeb by tasks.registering(Exec::class) {
    val repo = rootProject.projectDir.resolve("../..").canonicalFile
    commandLine("bash", repo.resolve("movil/scripts/bundle_web.sh").path)
    environment("DEST", projectDir.resolve("src/main/assets/www").path)
}
tasks.named("preBuild") { dependsOn(copiarWeb) }
