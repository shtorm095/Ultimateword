#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
rm -rf /tmp/wmtext121-src /tmp/wmtext111-src /tmp/wmtext112-src /tmp/wmtext113-src /tmp/wmtext114-src /tmp/wmtext115-src /tmp/wmtext116-src /tmp/wmtext117-src /tmp/wmtext118-src /tmp/wmtext119-src
mkdir -p /tmp/wmtext121-src

cat "$ROOT"/wearmemory_text_v100/source.part00 \
    "$ROOT"/wearmemory_text_v100/source.part01 \
    "$ROOT"/wearmemory_text_v100/source.part02 \
    "$ROOT"/wearmemory_text_v100/source.part03 \
    "$ROOT"/wearmemory_text_v100/source.part04 \
  | base64 --decode > /tmp/WearMemoryText_v1.0.0_Source.zip
unzip -t /tmp/WearMemoryText_v1.0.0_Source.zip
ditto -x -k /tmp/WearMemoryText_v1.0.0_Source.zip /tmp/wmtext121-src

base64 -D -i "$ROOT/wearmemory_text_v101/speech-fix.patch.gz.b64" -o /tmp/wmt101.patch.gz
echo 'b2077cfa763ab2f8e1b4d494ac61755921bdbc81d8c75f91ce1005591a10d6c5  /tmp/wmt101.patch.gz' | shasum -a 256 -c -
gunzip -c /tmp/wmt101.patch.gz > /tmp/wmt101.patch
cd /tmp/wmtext121-src
patch -p4 < /tmp/wmt101.patch
sed -i '' 's/^    let drive = TextDriveSync()/    var drive = TextDriveSync()/' WearMemoryText/TextAppModel.swift

base64 -D -i "$ROOT/wearmemory_text_v105/speech-fix-v105.patch.gz.b64" -o /tmp/wmt105.patch.gz
gunzip -c /tmp/wmt105.patch.gz > /tmp/wmtext105.patch
echo '863ad1a0d4fcade0faa474fb011a1e6a3a1cbe507754ddccc063f4a5775abc3b  /tmp/wmtext105.patch' | shasum -a 256 -c -
patch -p0 < /tmp/wmtext105.patch

cp "$ROOT/wearmemory_text_v106/TextProcessor.swift" WearMemoryText/TextProcessor.swift
cp "$ROOT/wearmemory_text_v106/TextProcessorJournal.swift" WearMemoryText/TextProcessorJournal.swift
python3 "$ROOT/wearmemory_text_v106/adaptive60_patch.py"
python3 "$ROOT/wearmemory_text_v108/siri101_102_patch.py"
python3 "$ROOT/wearmemory_text_v110/hybrid_pc_patch.py"

for v in 111 112 113 114 115 116 117 118 119; do ln -s /tmp/wmtext121-src "/tmp/wmtext${v}-src"; done
python3 "$ROOT/wearmemory_text_v111/ui_patch.py"
python3 "$ROOT/wearmemory_text_v112/playback_patch.py"
python3 "$ROOT/wearmemory_text_v112/playback_compile_fix.py"
python3 "$ROOT/wearmemory_text_v112/retention24_patch.py"
python3 "$ROOT/wearmemory_text_v113/final_text_patch.py"
python3 "$ROOT/wearmemory_text_v114/status_state_patch.py"
python3 "$ROOT/wearmemory_text_v115/tablet_status_patch.py"
python3 "$ROOT/wearmemory_text_v116/clear_stale_error_patch.py"
python3 "$ROOT/wearmemory_text_v117/clear_empty_queue_error_patch.py"
python3 "$ROOT/wearmemory_text_v118/embedded_m4a_metadata_patch.py"
python3 "$ROOT/wearmemory_text_v119/all_fixes_patch.py"
python3 "$ROOT/wearmemory_text_v121/whisper_production_patch.py"

SRC=/tmp/wmtext121-src/WearMemoryText
plutil -lint "$SRC/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SRC/Info.plist" | grep -Fx '1.2.2'
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Info.plist" | grep -Fx '22'
grep -Fq 'WhisperLocalRecognizer.transcribe(url: sourceURL)' "$SRC/TextProcessor.swift"
! grep -Fq 'guard speechAuthorization == .authorized' "$SRC/TextProcessor.swift"
grep -Fq 'Whisper Base · Deutsch · offline' "$SRC/TextProcessor.swift"
grep -Fq 'Deutsch (de)' "$SRC/ContentView.swift"
grep -Fq 'offline · CPU NoBLAS' "$SRC/ContentView.swift"
! grep -Fq 'LocalASRLabView' "$SRC/ContentView.swift"
grep -Fq 'params.language = "de"' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'params.n_threads = 1' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'params.greedy.best_of = 1' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'params.temperature_inc = 0.0f' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'whisper_full_get_token_p' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'GermanTranscriptPostProcessor.process' "$SRC/WhisperLocalRecognizer.swift"
grep -Fq 'Brüstungskanal' "$SRC/GermanTranscriptPostProcessor.swift"
grep -Fq 'VDE-AR-N 4100' "$SRC/GermanTranscriptPostProcessor.swift"
grep -Fq 'ambiguousCorrectionThreshold' "$SRC/GermanTranscriptPostProcessor.swift"
grep -q 'func writeSegmentText' "$SRC/TextProcessor.swift"
grep -q 'AVMutableComposition()' "$SRC/TextProcessor.swift"
grep -q 'func enqueueAudio(_ audioURL: URL)' "$SRC/TextDriveSync.swift"

rm -rf /tmp/wmtext121-native /tmp/whisper-src /tmp/whisper-build
mkdir -p /tmp/wmtext121-native/lib /tmp/wmtext121-native/include
git clone --filter=blob:none https://github.com/ggml-org/whisper.cpp.git /tmp/whisper-src
cd /tmp/whisper-src
git checkout 233fe1fc9b48a09e361d3594520838ca266537fe
test "$(git rev-parse HEAD)" = "233fe1fc9b48a09e361d3594520838ca266537fe"
grep -q 'MIT License' LICENSE

cmake -S /tmp/whisper-src -B /tmp/whisper-build -G Xcode \
  -DCMAKE_SYSTEM_NAME=iOS \
  -DCMAKE_OSX_SYSROOT=iphoneos \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=15.0 \
  -DBUILD_SHARED_LIBS=OFF \
  -DWHISPER_BUILD_EXAMPLES=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF \
  -DWHISPER_COREML=OFF \
  -DGGML_METAL=OFF \
  -DGGML_BLAS=OFF \
  -DGGML_ACCELERATE=OFF \
  -DGGML_OPENMP=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_CPU_KLEIDIAI=OFF
cmake --build /tmp/whisper-build --config Release --target whisper -- -quiet

WHISPER_LIB=$(find /tmp/whisper-build -name libwhisper.a -type f | head -1)
GGML_LIB=$(find /tmp/whisper-build -name libggml.a -type f | head -1)
BASE_LIB=$(find /tmp/whisper-build -name libggml-base.a -type f | head -1)
CPU_LIB=$(find /tmp/whisper-build -name libggml-cpu.a -type f | head -1)
for f in "$WHISPER_LIB" "$GGML_LIB" "$BASE_LIB" "$CPU_LIB"; do test -f "$f"; done
! find /tmp/whisper-build -name 'libggml-blas.a' -type f | grep -q .
/usr/bin/libtool -static -o /tmp/wmtext121-native/lib/libwmwhisper.a "$WHISPER_LIB" "$GGML_LIB" "$BASE_LIB" "$CPU_LIB"
lipo -archs /tmp/wmtext121-native/lib/libwmwhisper.a | grep -w arm64
cp -R /tmp/whisper-src/include/. /tmp/wmtext121-native/include/
cp -R /tmp/whisper-src/ggml/include/. /tmp/wmtext121-native/include/

MODEL=/tmp/ggml-base.bin
curl -L --fail --retry 5 --retry-delay 3 -o "$MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$MODEL" | shasum -c -

brew install xcodegen
cd /tmp/wmtext121-src
xcodegen generate
xcodebuild \
  -project WearMemoryText.xcodeproj \
  -scheme WearMemoryText \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/wmtext121-derived \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY='' \
  ARCHS=arm64 \
  ONLY_ACTIVE_ARCH=YES \
  IPHONEOS_DEPLOYMENT_TARGET=15.0 \
  clean build | tee /tmp/wmtext121-build.log

APP=/tmp/wmtext121-derived/Build/Products/Release-iphoneos/WearMemoryText.app
test -d "$APP"
/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$APP/Info.plist" | grep -Fx 'WearMemory Text'
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist" | grep -Fx 'local.pavel.WearMemoryText'
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Info.plist" | grep -Fx '1.2.2'
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Info.plist" | grep -Fx '22'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
lipo -archs "$APP/WearMemoryText" | grep -w arm64
cp /tmp/ggml-base.bin "$APP/ggml-base.bin"
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$APP/ggml-base.bin" | shasum -c -

codesign --force --sign - --entitlements /tmp/wmtext121-src/WearMemoryText/WearMemoryText.entitlements "$APP"
codesign --verify --deep --strict "$APP"
codesign -d --entitlements :- "$APP" > /tmp/wmtext121-entitlements.plist 2>&1
grep -q 'group.local.pavel.WearMemory' /tmp/wmtext121-entitlements.plist
grep -q 'TROLLTROLL.\*' /tmp/wmtext121-entitlements.plist

rm -rf /tmp/wmtext121-payload
mkdir -p /tmp/wmtext121-payload/Payload
ditto "$APP" /tmp/wmtext121-payload/Payload/WearMemoryText.app
cd /tmp/wmtext121-payload
zip -qry /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa Payload
unzip -t /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa
shasum -a 256 /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa > /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa.sha256
# Compatibility names keep the existing verified PR workflow upload step working.
cp /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa /tmp/WearMemoryText_v1.2.1b21_WhisperBase_CPU_NoBLAS_iOS15.ipa
cp /tmp/WearMemoryText_v1.2.2b22_GermanTechnical_Confidence_iOS15.ipa.sha256 /tmp/WearMemoryText_v1.2.1b21_WhisperBase_CPU_NoBLAS_iOS15.ipa.sha256

cd /tmp/wmtext121-src
zip -qry /tmp/WearMemoryText_v1.2.2_Source.zip WearMemoryText project.yml
unzip -t /tmp/WearMemoryText_v1.2.2_Source.zip
cp /tmp/WearMemoryText_v1.2.2_Source.zip /tmp/WearMemoryText_v1.2.1_Source.zip
