#!/usr/bin/env bash
# Builds the Android app from the web game. Requires a JDK (17+), curl, unzip and zip.
#
#   android/build.sh          -> dist/redlok.apk  (install directly on a phone)
#   android/build.sh aab      -> dist/redlok.aab  (upload to the Play Store)
#
# Environment:
#   RELEASE_KEYSTORE, RELEASE_KEY_ALIAS, RELEASE_STORE_PASSWORD, RELEASE_KEY_PASSWORD
#       sign with your own key (see android/release-key.sh). Without them the APK uses a debug
#       key and the AAB is left unsigned (the Play Store refuses both).
#   NO_LICENSED_MUSIC=1   leave out audio/sync-or-die.mp3; the game then plays its own synth track.
#   VERSION_CODE, VERSION_NAME
set -euo pipefail
FORMAT="${1:-apk}"
A="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$A")"
T="$A/.tools"
OUT="$A/build"
VERSION_CODE="${VERSION_CODE:-28}"
VERSION_NAME="${VERSION_NAME:-3.24}"

[ -x "$T/aapt2" ] && [ -s "$T/bundletool.jar" ] || "$A/fetch-tools.sh"

rm -rf "$OUT"
mkdir -p "$OUT/assets/www" "$OUT/classes"
cp -r "$ROOT/index.html" "$ROOT/manifest.webmanifest" "$ROOT/css" "$ROOT/js" "$ROOT/fonts" "$ROOT/assets" "$OUT/assets/www/"
if [ "${NO_LICENSED_MUSIC:-0}" != "1" ]; then
  cp -r "$ROOT/audio" "$OUT/assets/www/"
else
  echo "Musique sous licence exclue : piste Synthé uniquement."
fi

# Code
javac -nowarn -Xlint:-options -source 8 -target 8 -bootclasspath "$T/android.jar" \
  -d "$OUT/classes" $(find "$A/src" -name '*.java')
java -cp "$T/r8.jar" com.android.tools.r8.D8 --release --min-api 24 \
  --lib "$T/android.jar" --output "$OUT" $(find "$OUT/classes" -name '*.class')

# Resources + manifest
"$T/aapt2" compile --dir "$A/res" -o "$OUT/res.zip"
LINK=(-I "$T/android.jar" --manifest "$A/AndroidManifest.xml" -A "$OUT/assets"
      --min-sdk-version 24 --target-sdk-version 34
      --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" "$OUT/res.zip")
mkdir -p "$ROOT/dist"
HAS_KEY=0
[ -n "${RELEASE_KEYSTORE:-}" ] && HAS_KEY=1

if [ "$FORMAT" = "aab" ]; then
  "$T/aapt2" link --proto-format -o "$OUT/proto.apk" "${LINK[@]}"
  M="$OUT/base"; mkdir -p "$M/manifest" "$M/dex"
  (cd "$M" && unzip -q "$OUT/proto.apk")
  mv "$M/AndroidManifest.xml" "$M/manifest/"
  cp "$OUT/classes.dex" "$M/dex/"
  (cd "$M" && zip -qr "$OUT/base.zip" .)
  AAB="$ROOT/dist/redlok.aab"
  rm -f "$AAB"
  java -jar "$T/bundletool.jar" build-bundle --modules="$OUT/base.zip" --output="$AAB"
  if [ "$HAS_KEY" = 1 ]; then
    jarsigner -sigalg SHA256withRSA -digestalg SHA-256 -keystore "$RELEASE_KEYSTORE" \
      -storepass "$RELEASE_STORE_PASSWORD" -keypass "${RELEASE_KEY_PASSWORD:-$RELEASE_STORE_PASSWORD}" \
      "$AAB" "$RELEASE_KEY_ALIAS" >/dev/null
    echo "AAB signé : $AAB"
  else
    echo "AAB NON signé (aucune clé fournie) : $AAB"
  fi
  exit 0
fi

"$T/aapt2" link -o "$OUT/unsigned.apk" "${LINK[@]}"
(cd "$OUT" && zip -q unsigned.apk classes.dex)
SIGN=(-a "$OUT/unsigned.apk" -o "$OUT/signed" --allowResign)
if [ "$HAS_KEY" = 1 ]; then
  SIGN+=(--ks "$RELEASE_KEYSTORE" --ksAlias "$RELEASE_KEY_ALIAS" --ksPass "$RELEASE_STORE_PASSWORD" --ksKeyPass "${RELEASE_KEY_PASSWORD:-$RELEASE_STORE_PASSWORD}")
fi
java -jar "$T/signer.jar" "${SIGN[@]}" >/dev/null
cp "$OUT"/signed/*.apk "$ROOT/dist/redlok.apk"
echo "APK ($([ "$HAS_KEY" = 1 ] && echo "clé de publication" || echo "clé de debug")) : $ROOT/dist/redlok.apk"
