#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
WORK=/tmp/wm127-patcher
rm -rf "$WORK"
mkdir -p "$WORK/artifact" "$WORK/Payload/WearMemoryTextPatch127.app"

export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
gh api repos/$GITHUB_REPOSITORY/actions/artifacts/9492929023/zip > "$WORK/full-artifact.zip"
unzip -q "$WORK/full-artifact.zip" -d "$WORK/artifact"
FULL_IPA=$(find "$WORK/artifact" -maxdepth 1 -type f -name '*.ipa' | head -1)
test -n "$FULL_IPA"
echo 'e0e1fb86416031a54b7fc0ac799e74fa5a7fd6a6d40d2d72f9c25137ac4dcc0d  '"$FULL_IPA" | shasum -a 256 -c -

unzip -p "$FULL_IPA" 'Payload/WearMemoryText.app/WearMemoryText' > "$WORK/target-executable"
test "$(stat -f%z "$WORK/target-executable")" = "2671760"
echo '68fd375feda10389c46cb62388f75c7f200f68522fe63fb3555b8d6c65fa5d61  '"$WORK/target-executable" | shasum -a 256 -c -

codesign -d --entitlements :- "$WORK/target-executable" > "$WORK/target-entitlements.plist" 2>/dev/null
plutil -lint "$WORK/target-entitlements.plist"
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.primitiveattribute' "$WORK/target-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.assertions.frontboard' "$WORK/target-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.process-state' "$WORK/target-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :platform-application' "$WORK/target-entitlements.plist" | grep -Fx 'true'
strings "$WORK/target-executable" > "$WORK/target-strings.txt"
grep -Fq 'RunningBoardServices.framework/RunningBoardServices' "$WORK/target-strings.txt"
grep -Fq 'RBSLegacyAttribute' "$WORK/target-strings.txt"

# v6 regression guard: TrollStore re-signing is allowed to change Mach-O file size.
grep -Fq 'patchedExecSize > 2500000ULL' "$ROOT/wearmemory_text_patch127/patchhelper.m"
grep -Fq 'patchedExecSize < 3000000ULL' "$ROOT/wearmemory_text_patch127/patchhelper.m"
! grep -Fq 'FileSize([patched stringByAppendingPathComponent:@"WearMemoryText"]) == PayloadExecutableSize' "$ROOT/wearmemory_text_patch127/patchhelper.m"
grep -Fq 'Patch v6' "$ROOT/wearmemory_text_patch127/patcher_main.m"

python3 - "$WORK/target-executable" "$WORK/target-executable.xor" <<'PY'
from pathlib import Path
import sys
src = bytearray(Path(sys.argv[1]).read_bytes())
for i in range(len(src)):
    src[i] ^= 0xA5
Path(sys.argv[2]).write_bytes(src)
PY

test "$(stat -f%z "$WORK/target-executable.xor")" = "2671760"

SDK=$(xcrun --sdk iphoneos --show-sdk-path)
APP="$WORK/Payload/WearMemoryTextPatch127.app"

xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation "$ROOT/wearmemory_text_patch127/patchhelper.m" -o "$APP/patchhelper"

xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation -framework UIKit "$ROOT/wearmemory_text_patch127/patcher_main.m" \
  -o "$APP/WearMemoryTextPatch127"

cp "$WORK/target-executable.xor" "$APP/target-executable.xor"
chmod 0755 "$APP/WearMemoryTextPatch127" "$APP/patchhelper"
chmod 0644 "$APP/target-executable.xor"

cat > "$APP/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>WearMemoryTextPatch127</string>
<key>CFBundleIdentifier</key><string>local.pavel.WearMemoryTextPatch127</string>
<key>CFBundleName</key><string>Text Patch</string>
<key>CFBundleDisplayName</key><string>Text 1.2.7 Patch v6</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.1</string>
<key>CFBundleVersion</key><string>6</string>
<key>MinimumOSVersion</key><string>15.0</string>
<key>LSRequiresIPhoneOS</key><true/>
<key>UIDeviceFamily</key><array><integer>1</integer><integer>2</integer></array>
<key>UISupportedInterfaceOrientations</key><array><string>UIInterfaceOrientationPortrait</string></array>
<key>UISupportedInterfaceOrientations~ipad</key><array><string>UIInterfaceOrientationPortrait</string><string>UIInterfaceOrientationPortraitUpsideDown</string><string>UIInterfaceOrientationLandscapeLeft</string><string>UIInterfaceOrientationLandscapeRight</string></array>
<key>TSRootBinaries</key><array><string>patchhelper</string></array>
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
<key>platform-application</key><true/>
<key>com.apple.private.security.no-sandbox</key><true/>
<key>com.apple.private.persona-mgmt</key><true/>
</dict></plist>
PLIST

cat > "$WORK/roothelper.entitlements" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>platform-application</key><true/>
<key>com.apple.private.security.container-required</key><false/>
<key>com.apple.private.security.no-sandbox</key><true/>
<key>com.apple.private.security.container-manager</key><true/>
<key>com.apple.private.MobileContainerManager.allowed</key><true/>
<key>com.apple.private.security.storage.AppBundles</key><true/>
<key>com.apple.private.security.storage.MobileDocuments</key><true/>
<key>com.apple.private.security.storage-exempt.heritable</key><true/>
</dict></plist>
PLIST

codesign --force --sign - --entitlements "$WORK/roothelper.entitlements" "$APP/patchhelper"
codesign --force --sign - --entitlements "$WORK/patcher.entitlements" "$APP"
codesign --verify --deep --strict "$APP"

codesign -d --entitlements :- "$APP" > "$WORK/gui-entitlements.plist" 2>/dev/null
codesign -d --entitlements :- "$APP/patchhelper" > "$WORK/helper-entitlements.plist" 2>/dev/null
plutil -lint "$WORK/gui-entitlements.plist"
plutil -lint "$WORK/helper-entitlements.plist"
/usr/libexec/PlistBuddy -c 'Print :platform-application' "$WORK/gui-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.private.persona-mgmt' "$WORK/gui-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :platform-application' "$WORK/helper-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.private.security.container-required' "$WORK/helper-entitlements.plist" | grep -Fx 'false'
/usr/libexec/PlistBuddy -c 'Print :com.apple.private.security.storage.AppBundles' "$WORK/helper-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :TSRootBinaries:0' "$APP/Info.plist" | grep -Fx 'patchhelper'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$APP/Info.plist" | grep -Fx 'Text 1.2.7 Patch v6'
file "$APP/WearMemoryTextPatch127" | grep -q 'arm64'
file "$APP/patchhelper" | grep -q 'arm64'

python3 - "$APP/target-executable.xor" "$WORK/decoded-check" <<'PY'
from pathlib import Path
import sys
src = bytearray(Path(sys.argv[1]).read_bytes())
for i in range(len(src)):
    src[i] ^= 0xA5
Path(sys.argv[2]).write_bytes(src)
PY
echo '68fd375feda10389c46cb62388f75c7f200f68522fe63fb3555b8d6c65fa5d61  '"$WORK/decoded-check" | shasum -a 256 -c -

OUT=/tmp/WearMemoryText_1.2.7_InstallPatch_v6_RunningBoard_TrollStore_iOS15.ipa
rm -f "$OUT" "$OUT.sha256"
cd "$WORK"
zip -qry "$OUT" Payload
unzip -t "$OUT"
shasum -a 256 "$OUT" > "$OUT.sha256"

! unzip -l "$OUT" | grep -q 'ggml-base.bin'
! unzip -l "$OUT" | grep -q 'ggml-small-q5_1.bin'
unzip -l "$OUT" > "$WORK/ipa-list.txt"
grep -Fq 'Payload/WearMemoryTextPatch127.app/patchhelper' "$WORK/ipa-list.txt"
SIZE=$(stat -f%z "$OUT")
test "$SIZE" -lt 10000000
printf 'Patch IPA v6 size: %s bytes\n' "$SIZE"
cat "$OUT.sha256"
