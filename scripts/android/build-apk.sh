#!/usr/bin/env bash
# Build SupermarketMobile-<ver>.apk WITHOUT Gradle/Android Studio.
#
# Toolchain (all fetched from public package registries — no Google/Maven access needed):
#   java      : jdk4py (PyPI)                  → JRE 25
#   javac     : ecj.jar (Eclipse batch compiler)
#   aapt2     : aaptjs3 (npm) linux x64 binary
#   d8        : com.android.tools.r8 classes bundled in bundletool-all (MobSF PyPI wheel)
#   apksigner : apksigner.jar (MobSF wheel)
#   android.jar: platform 34 stub jar (must be provided; see fetch-tools.sh)
#
# Usage: TOOLS=/path/to/tools scripts/android/build-apk.sh [out-dir]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="${TOOLS:-/tmp/atools}"
OUT="${1:-$ROOT/installer/output}"
JAVA="${JAVA:-$TOOLS/jdk/bin/java}"
KEYTOOL="${KEYTOOL:-$TOOLS/jdk/bin/keytool}"
ECJ="$TOOLS/ecj.jar"; AAPT2="$TOOLS/aapt2"; D8JAR="$TOOLS/d8.jar"; APKSIGNER="$TOOLS/apksigner.jar"; ANDROID_JAR="$TOOLS/android.jar"
for f in "$JAVA" "$ECJ" "$AAPT2" "$D8JAR" "$APKSIGNER" "$ANDROID_JAR"; do [ -e "$f" ] || { echo "missing tool: $f (run scripts/android/fetch-tools.sh)"; exit 1; }; done

VER=$(sed -nE 's/__version__\s*=\s*"([^"]+)"/\1/p' "$ROOT/backend/app/__init__.py")
IFS=. read -r MA MI PA <<<"$VER"; CODE=$((MA*10000 + MI*100 + PA))
APP="$ROOT/mobile-android/app/src/main"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
mkdir -p "$W/gen" "$W/classes" "$W/dex" "$OUT"

echo "== 1/6 bundle web app into assets/www (version $VER)"
ASSETS="$W/assets/www"; mkdir -p "$ASSETS/mobile" "$ASSETS/fonts" "$ASSETS/icons"
cp "$ROOT"/frontend/mobile/*.{html,js,css} "$ASSETS/mobile/"
cp "$ROOT"/frontend/jalali.js "$ASSETS/"
cp "$ROOT"/frontend/fonts/*.woff2 "$ROOT"/frontend/fonts/OFL-Vazirmatn.txt "$ASSETS/fonts/"
cp "$ROOT"/frontend/icons/* "$ASSETS/icons/"
echo "{\"version\":\"$VER\",\"built_at\":\"$(date -u +%FT%TZ)\"}" > "$ASSETS/mobile/build.json"

echo "== 2/6 resources (aapt2)"
"$AAPT2" compile --dir "$APP/res" -o "$W/res.zip"
"$AAPT2" link -o "$W/base.apk" -I "$ANDROID_JAR" --manifest "$APP/AndroidManifest.xml" \
  --java "$W/gen" -R "$W/res.zip" --auto-add-overlay \
  --version-code "$CODE" --version-name "$VER" --min-sdk-version 24 --target-sdk-version 34 -A "$W/assets"

echo "== 3/6 compile Java (ecj)"
mkdir -p "$W/gen/ir/khajavy/supermarket"
cat > "$W/gen/ir/khajavy/supermarket/Version.java" <<JAVA
package ir.khajavy.supermarket;
public final class Version { public static final String NAME = "$VER"; public static final int CODE = $CODE; private Version() {} }
JAVA
"$JAVA" -jar "$ECJ" -8 -nowarn -proc:none -cp "$ANDROID_JAR" -d "$W/classes" "$W/gen" "$APP/java"

echo "== 4/6 dex (d8)"
"$JAVA" -cp "$D8JAR" com.android.tools.r8.D8 --release --lib "$ANDROID_JAR" --min-api 24 --output "$W/dex" $(find "$W/classes" -name '*.class')

echo "== 5/6 package + align"
cp "$W/base.apk" "$W/unsigned.apk"
( cd "$W/dex" && zip -q "$W/unsigned.apk" classes.dex )
if [ -x "$TOOLS/zipalign" ]; then "$TOOLS/zipalign" -f -p 4 "$W/unsigned.apk" "$W/aligned.apk"; else cp "$W/unsigned.apk" "$W/aligned.apk"; fi

echo "== 6/6 sign (apksigner v2+v3)"
KS="${SUPERMARKET_KEYSTORE:-$ROOT/installer/output/supermarket-release.jks}"
KS_PASS="${SUPERMARKET_KEYSTORE_PASSWORD:-supermarket}"; KS_ALIAS="${SUPERMARKET_KEY_ALIAS:-supermarket}"; KEY_PASS="${SUPERMARKET_KEY_PASSWORD:-$KS_PASS}"
if [ ! -f "$KS" ]; then
  echo "   generating keystore $KS (keep it! updates must be signed with the same key)"
  "$KEYTOOL" -genkeypair -keystore "$KS" -storepass "$KS_PASS" -keypass "$KEY_PASS" -alias "$KS_ALIAS" \
    -dname "CN=Khajavy Supermarket, O=Khajavy, C=IR" -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
fi
APK="$OUT/SupermarketMobile-$VER.apk"
"$JAVA" -jar "$APKSIGNER" sign --ks "$KS" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KEY_PASS" --ks-key-alias "$KS_ALIAS" --out "$APK" "$W/aligned.apk" 2>/dev/null
"$JAVA" -jar "$APKSIGNER" verify --print-certs "$APK" 2>/dev/null | head -3
( cd "$OUT" && sha256sum "$(basename "$APK")" > "$(basename "$APK").sha256" )
echo "OK → $APK ($(du -h "$APK" | cut -f1))"
