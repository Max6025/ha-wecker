plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "de.starnberg.hawecker"
    compileSdk = 36

    defaultConfig {
        applicationId = "de.starnberg.hawecker"
        minSdk = 26
        targetSdk = 35
        versionCode = 15
        versionName = "2.6"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // Release wird mit dem Debug-Key signiert, damit die APK direkt
            // installierbar ist (Sideload, kein Play Store).
            signingConfig = signingConfigs.getByName("debug")
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources.excludes += setOf("META-INF/*.kotlin_module", "kotlin/**", "DebugProbesKt.bin")
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
}
