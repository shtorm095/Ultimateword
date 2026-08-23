#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
WORK=/tmp/wm126-patcher
rm -rf "$WORK"
mkdir -p "$WORK/artifact" "$WORK/Payload/WearMemoryTextPatch.app"

# Reuse the already verified full 1.2.6 build only as a build-time source for the
# replacement executable. The final patch IPA does not contain either Whisper model.
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
gh api repos/$GITHUB_REPOSITORY/actions/artifacts/9484486181/zip > "$WORK/full-artifact.zip"
unzip -q "$WORK/full-artifact.zip" -d "$WORK/artifact"
FULL_IPA=$(find "$WORK/artifact" -maxdepth 1 -type f -name '*.ipa' | head -1)
test -n "$FULL_IPA"
echo 'a6d3c1799f6ddc4709d31b03103d41f2237480149b17791284a75bfdf1174208  '"$FULL_IPA" | shasum -a 256 -c -
unzip -p "$FULL_IPA" 'Payload/WearMemoryText.app/WearMemoryText' > "$WORK/target-executable"
test "$(stat -f%z "$WORK/target-executable")" = "2675216"

# Hide the Mach-O magic while the replacement executable is embedded in the patcher.
python3 - "$WORK/target-executable" "$WORK/target-executable.xor" <<'PY'
from pathlib import Path
import sys
src = bytearray(Path(sys.argv[1]).read_bytes())
for i in range(len(src)):
    src[i] ^= 0xA5
Path(sys.argv[2]).write_bytes(src)
PY

test "$(stat -f%z "$WORK/target-executable.xor")" = "2675216"

SDK=$(xcrun --sdk iphoneos --show-sdk-path)
APP="$WORK/Payload/WearMemoryTextPatch.app"

# Compile the patch logic into the app's own Mach-O. The UI process then spawns this
# already-trusted app executable as root, matching TrollStore's embedded-root-helper pattern.
xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation -Dmain=WearMemoryPatchHelperMain -c \
  "$ROOT/wearmemory_text_patch126/patchhelper.m" -o "$WORK/patchhelper.o"

xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation -framework UIKit \
  "$ROOT/wearmemory_text_patch126/patcher_main.m" "$WORK/patchhelper.o" \
  -o "$APP/WearMemoryTextPatch"

cp "$WORK/target-executable.xor" "$APP/target-executable.xor"
chmod 0755 "$APP/WearMemoryTextPatch"
chmod 0644 "$APP/target-executable.xor"

cat > "$APP/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>WearMemoryTextPatch</string>
<key>CFBundleIdentifier</key><string>local.pavel.WearMemoryTextPatch126</string>
<key>CFBundleName</key><string>Text Patch</string>
<key>CFBundleDisplayName</key><string>Text 1.2.6 Patch v2</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.1</string>
<key>CFBundleVersion</key><string>2</string>
<key>MinimumOSVersion</key><string>15.0</string>
<key>LSRequiresIPhoneOS</key><true/>
<key>UIDeviceFamily</key><array><integer>1</integer><integer>2</integer></array>
<key>UISupportedInterfaceOrientations</key><array><string>UIInterfaceOrientationPortrait</string></array>
<key>UISupportedInterfaceOrientations~ipad</key><array><string>UIInterfaceOrientationPortrait</string><string>UIInterfaceOrientationPortraitUpsideDown</string><string>UIInterfaceOrientationLandscapeLeft</string><string>UIInterfaceOrientationLandscapeRight</string></array>
</dict></plist>
PLIST

cat > "$WORK/patcher.entitlements" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>application-identifier</key><string>TROLLTROLL.*</string>
<key>com.apple.developer.team-identifier</key><string>TROLLTROLL</string>
<key>get-task-allow</key><true/>
<key>keychain-access-groups</key><array><string>TROLLTROLL.*</string><string>com.apple.token</string></array>
<key>com.apple.private.security.no-sandbox</key><true/>
<key>com.apple.private.persona-mgmt</key><true/>
<key>com.apple.private.security.storage.AppDataContainers</key><true/>
</dict></plist>
PLIST

codesign --force --sign - --entitlements "$WORK/patcher.entitlements" "$APP"
codesign --verify --deep --strict "$APP"

OUT=/tmp/WearMemoryText_1.2.6_InstallPatch_v2_TrollStore_iOS15.ipa
rm -f "$OUT" "$OUT.sha256"
cd "$WORK"
zip -qry "$OUT" Payload
unzip -t "$OUT"
shasum -a 256 "$OUT" > "$OUT.sha256"

# The patch must stay small and must not accidentally contain either model or a
# second helper Mach-O (the root entrypoint is embedded into the main executable).
! unzip -l "$OUT" | grep -q 'ggml-base.bin'
! unzip -l "$OUT" | grep -q 'ggml-small-q5_1.bin'
! unzip -l "$OUT" | grep -q '/patchhelper$'
SIZE=$(stat -f%z "$OUT")
test "$SIZE" -lt 10000000
printf 'Patch IPA v2 size: %s bytes\n' "$SIZE"
cat "$OUT.sha256"
