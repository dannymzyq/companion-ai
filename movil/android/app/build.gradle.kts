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
        versionCode = 6
        versionName = "0.11.1"
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
    androidResources { noCompress += listOf("vrm", "glb", "wav", "bin") }
}

dependencies {
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.activity:activity-ktx:1.13.0")
    implementation("androidx.webkit:webkit:1.18.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
}

// Copia multiplataforma (Windows, macOS, Linux sin depender de bash/rsync) de web/ y movil/core a assets/www.
val copiarWeb by tasks.registering {
    val repo = rootProject.projectDir.resolve("../..").canonicalFile
    val dest = projectDir.resolve("src/main/assets/www")
    inputs.dir(repo.resolve("web"))
    inputs.dir(repo.resolve("movil/core"))
    outputs.dir(dest)
    doLast {
        dest.deleteRecursively()
        File(dest, "models").mkdirs()
        File(dest, "data").mkdirs()
        File(dest, "voices/previews").mkdirs()
        project.copy {
            from(repo.resolve("web")) { exclude("vendor/**") }
            into(dest)
        }
        val movilVendor = repo.resolve("movil/vendor")
        val vendorSrc = if (File(movilVendor, "three-vrm/three-vrm.module.min.js").isFile) movilVendor else repo.resolve("web/vendor")
        project.copy {
            from(vendorSrc)
            into(File(dest, "vendor"))
        }
        project.copy {
            from(repo.resolve("movil/core")) {
                exclude("**/*.test.js", "pruebas.mjs")
            }
            into(File(dest, "core"))
        }
        for (vrmName in listOf("avatar1.vrm", "avatar2.vrm")) {
            val f = repo.resolve("models/$vrmName")
            if (f.isFile) f.copyTo(File(dest, "models/$vrmName"), overwrite = true)
        }
        val previews = repo.resolve("voices/previews")
        if (previews.isDirectory) {
            project.copy {
                from(previews)
                into(File(dest, "voices/previews"))
            }
        }
        repo.resolve("personas/mika.json").copyTo(File(dest, "data/persona.json"), overwrite = true)
        repo.resolve("personas/personalidades.json").copyTo(File(dest, "data/personalidades.json"), overwrite = true)
        repo.resolve("voices.json").copyTo(File(dest, "data/voices.json"), overwrite = true)
    }
}
tasks.named("preBuild") { dependsOn(copiarWeb) }
