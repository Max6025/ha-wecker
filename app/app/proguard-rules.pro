-keepattributes SourceFile,LineNumberTable
-dontwarn org.json.**

# Bruecke WebView -> Kotlin: Methoden muessen ihren Namen behalten
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
