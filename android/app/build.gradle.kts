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
            java.srcDirs("src/main/java", sdlJavaDir)
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
            // Load `libblender.so` directly from the APK (page aligned, uncompressed).
            useLegacyPackaging = false
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
