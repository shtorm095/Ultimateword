#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
WORK=/tmp/wm126-patcher
rm -rf "$WORK"
mkdir -p "$WORK/artifact" "$WORK/Payload/WearMemoryTextPatch.app"

# Use the already verified full 1.2.6 build only as build-time source for the
# replacement executable. The patch IPA itself must not contain Whisper models.
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
gh api repos/$GITHUB_REPOSITORY/actions/artifacts/9484486181/zip > "$WORK/full-artifact.zip"
unzip -q "$WORK/full-artifact.zip" -d "$WORK/artifact"
FULL_IPA=$(find "$WORK/artifact" -maxdepth 1 -type f -name '*.ipa' | head -1)
test -n "$FULL_IPA"
echo 'a6d3c1799f6ddc4709d31b03103d41f2237480149b17791284a75bfdf1174208  '"$FULL_IPA" | shasum -a 256 -c -
unzip -p "$FULL_IPA" 'Payload/WearMemoryText.app/WearMemoryText' > "$WORK/target-executable"
test "$(stat -f%z "$WORK/target-executable")" = "2675216"
echo '873b160901349e476b56f13640f937ddde935ab72452715a8b46a91845b4a13a  '"$WORK/target-executable" | shasum -a 256 -c -

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

# Keep the GUI executable and root helper separate. This is the same architecture
# used by TrollStore itself: the helper is declared through TSRootBinaries.
xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation "$ROOT/wearmemory_text_patch126/patchhelper.m" -o "$APP/patchhelper"

xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=15.0 -fobjc-arc -isysroot "$SDK" \
  -framework Foundation -framework UIKit "$ROOT/wearmemory_text_patch126/patcher_main.m" \
  -o "$APP/WearMemoryTextPatch"

cp "$WORK/target-executable.xor" "$APP/target-executable.xor"
chmod 0755 "$APP/WearMemoryTextPatch" "$APP/patchhelper"
chmod 0644 "$APP/target-executable.xor"

cat > "$APP/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>WearMemoryTextPatch</string>
<key>CFBundleIdentifier</key><string>local.pavel.WearMemoryTextPatch126</string>
<key>CFBundleName</key><string>Text Patch</string>
<key>CFBundleDisplayName</key><string>Text 1.2.6 Patch v4</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.3</string>
<key>CFBundleVersion</key><string>4</string>
<key>MinimumOSVersion</key><string>15.0</string>
<key>LSRequiresIPhoneOS</key><true/>
<key>UIDeviceFamily</key><array><integer>1</integer><integer>2</integer></array>
<key>UISupportedInterfaceOrientations</key><array><string>UIInterfaceOrientationPortrait</string></array>
<key>UISupportedInterfaceOrientations~ipad</key><array><string>UIInterfaceOrientationPortrait</string><string>UIInterfaceOrientationPortraitUpsideDown</string><string>UIInterfaceOrientationLandscapeLeft</string><string>UIInterfaceOrientationLandscapeRight</string></array>
<key>TSRootBinaries</key><array><string>patchhelper</string></array>
</dict></plist>
PLIST

# GUI process: same small privileged set that successfully launched in v1 and
# matches TrollStore's persona-spawn pattern.
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

# Root helper: use TrollStore RootHelper's relevant filesystem/container privileges.
# v1 was incorrectly ad-hoc signed with NO entitlement blob at all.
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
/usr/libexec/PlistBuddy -c 'Print :com.apple.private.security.no-sandbox' "$WORK/helper-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.private.security.storage.AppBundles' "$WORK/helper-entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :TSRootBinaries:0' "$APP/Info.plist" | grep -Fx 'patchhelper'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
file "$APP/WearMemoryTextPatch" | grep -q 'arm64'
file "$APP/patchhelper" | grep -q 'arm64'

OUT=/tmp/WearMemoryText_1.2.6_InstallPatch_v4_TrollStore_iOS15.ipa
rm -f "$OUT" "$OUT.sha256"
cd "$WORK"
zip -qry "$OUT" Payload
unzip -t "$OUT"
shasum -a 256 "$OUT" > "$OUT.sha256"

! unzip -l "$OUT" | grep -q 'ggml-base.bin'
! unzip -l "$OUT" | grep -q 'ggml-small-q5_1.bin'
unzip -l "$OUT" | grep -q 'Payload/WearMemoryTextPatch.app/patchhelper'
SIZE=$(stat -f%z "$OUT")
test "$SIZE" -lt 10000000
printf 'Patch IPA v4 size: %s bytes\n' "$SIZE"
cat "$OUT.sha256"
