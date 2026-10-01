plugins {
    id("com.android.application")
}

// Outputs of the native build, see `scripts/package_apk.sh`.
//   blender.nativeLibsDir : contains `arm64-v8a/libblender.so`
//   blender.assetsDir     : contains `blender_data.zip` and `blender_data.version`
//   blender.sdlJavaDir    : SDL3's Java sources (`org/libsdl/app/*.java`)
val workDir = rootProject.file("../_work")
val nativeLibsDir = (findProperty("blender.nativeLibsDir") as String?) ?: "$workDir/apk/jniLibs"
val assetsDir = (findProperty("blender.assetsDir") as String?) ?: "$workDir/apk/assets"
val sdlJavaDir = (findProperty("blender.sdlJavaDir") as String?)
    ?: "$workDir/android_arm64_libs/share/sdl3-java"
// SDL3's Java sources, with changes:
// - A larger stack for the thread running Blender (SDL starts it with the default stack size of
//   about 1MB, desktop systems give the main thread 8MB): deep recursion (Python, node trees,
//   file formats) would overflow it.
// - When the activity is destroyed, SDL waits 1 second for its thread, then destroys its event
//   queue, also when the thread still runs: Blender (busy writing the auto-save when the
//   application went to the background) would never get the quit event and then wait for events
//   forever. Blender exits when it gets it (the process ends while the activity waits).
val sdlJavaGenDir = layout.buildDirectory.dir("generated/sdl-java").get().asFile
val sdlThreadStackSize = 16L * 1024 * 1024
val sdlThreadQuitTimeoutMs = 8000L
val sdlJavaReplacements = mapOf(
    "new Thread(new SDLMain(), \"SDLThread\")" to
        "new Thread(null, new SDLMain(), \"SDLThread\", ${sdlThreadStackSize}L)",
    "SDLActivity.mSDLThread.join(1000);" to
        "SDLActivity.mSDLThread.join(${sdlThreadQuitTimeoutMs}L);",
    "        SDLActivity.nativeQuit();" to
        "        if (SDLActivity.mSDLThread == null || !SDLActivity.mSDLThread.isAlive()) SDLActivity.nativeQuit();",
)
val prepareSdlJava by tasks.registering(Sync::class) {
    from(sdlJavaDir)
    into(sdlJavaGenDir)
    filesMatching("**/SDLActivity.java") {
        filter { line ->
            sdlJavaReplacements.entries.fold(line) { text, (from, to) -> text.replace(from, to) }
        }
    }
    doLast {
        val activity = sdlJavaGenDir.walk().first { it.name == "SDLActivity.java" }.readText()
        for (to in sdlJavaReplacements.values) {
            check(activity.split(to).size == 2) {
                "SDLActivity.java changed (expected \"$to\" once), update prepareSdlJava"
            }
        }
    }
}
tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(prepareSdlJava) }

val blenderVersion = (findProperty("blender.version") as String?) ?: "5.2.2"
val portRevision = ((findProperty("blender.portRevision") as String?) ?: "1").toInt()

// 5.2.2 revision 1 -> 50202 * 100 + 1
val blenderVersionCode = blenderVersion.split(".").map { it.toInt() }
    .let { (major, minor, patch) -> (major * 10000 + minor * 100 + patch) * 100 + portRevision }

android {
    namespace = "com.github.sakkijarvenpolkka.blender"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.github.sakkijarvenpolkka.blender"
        // Galaxy S22 series shipped with Android 12 (API 31).
        minSdk = 31
        targetSdk = 35
        versionCode = blenderVersionCode
        versionName = "$blenderVersion-android.$portRevision"

        ndk {
            abiFilters += "arm64-v8a"
        }
        buildConfigField("String", "BLENDER_VERSION", "\"$blenderVersion\"")
    }

    buildFeatures {
        buildConfig = true
    }

    sourceSets {
        getByName("main") {
            java.srcDirs("src/main/java", sdlJavaGenDir)
            jniLibs.srcDirs(nativeLibsDir)
            assets.srcDirs(assetsDir)
        }
    }

    androidResources {
        // The data archive is extracted on first start, storing it uncompressed avoids
        // compressing it twice.
        noCompress += listOf("zip")
    }

    packaging {
        jniLibs {
            // Extract the native libraries when installing: the Python interpreter executable
            // (`libblender_python.so`) must be a file to be executed. Also makes the APK smaller
            // (compressed libraries).
            useLegacyPackaging = true
        }
    }

    signingConfigs {
        create("release") {
            val keystore = System.getenv("BLENDER_ANDROID_KEYSTORE")
            if (keystore != null) {
                storeFile = file(keystore)
                storePassword = System.getenv("BLENDER_ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("BLENDER_ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("BLENDER_ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            // Without a release key the APK is signed with the debug key, which is fine for
            // installing it directly (side-loading).
            signingConfig = if (System.getenv("BLENDER_ANDROID_KEYSTORE") != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}
