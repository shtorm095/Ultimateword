#!/bin/bash
set -euo pipefail

WORK=/tmp/wm-text-keeper
THEOS=/tmp/theos
rm -rf "$WORK" "$THEOS"
mkdir -p "$WORK"

# Build from the GPLv3 ImmortalizerTS implementation that is known to keep
# TrollStore apps foregrounded by creating a FrontBoard scene. Pin the exact
# upstream revision used by this build in the artifact metadata.
git clone --depth 1 https://github.com/sergealagon/ImmortalizerTS.git "$WORK/ImmortalizerTS"
UPSTREAM_SHA=$(git -C "$WORK/ImmortalizerTS" rev-parse HEAD)
printf '%s\n' "$UPSTREAM_SHA" > "$WORK/IMMORTALIZERTS_UPSTREAM_COMMIT.txt"

# Theos + SDKs are used because the upstream app links private iOS frameworks.
git clone --recursive --depth 1 https://github.com/theos/theos.git "$THEOS"
rm -rf "$THEOS/sdks"
git clone --depth 1 https://github.com/theos/sdks.git "$THEOS/sdks"
export THEOS

if ! command -v ldid >/dev/null 2>&1; then
  brew install ldid
fi
command -v ldid

PROJ="$WORK/ImmortalizerTS"

python3 - "$PROJ" <<'PY'
from pathlib import Path
import plistlib, sys

p = Path(sys.argv[1])
vc = p / 'src/ViewController.m'
info = p / 'Resources/Info.plist'
make = p / 'Makefile'

s = vc.read_text()
marker = '    [self setupCollectionView];\n'
inject = r'''    [self setupCollectionView];

    // WearMemory Text Keeper: automatically immortalize only WearMemory Text.
    // This uses the same FrontBoard scene path as ImmortalizerTS itself.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(600 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
        LSApplicationProxy *textApp = nil;
        for (LSApplicationProxy *candidate in [[LSApplicationWorkspace defaultWorkspace] allInstalledApplications]) {
            if ([candidate.bundleIdentifier isEqualToString:@"local.pavel.WearMemoryText"]) {
                textApp = candidate;
                break;
            }
        }
        if (!textApp) {
            UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"WearMemory Text не найден"
                message:@"Сначала установи WearMemory Text через TrollStore."
                preferredStyle:UIAlertControllerStyleAlert];
            [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
            [self presentViewController:alert animated:YES completion:nil];
            return;
        }

        if (![self.selectedApps containsObject:textApp]) {
            [self initializeNewSceneForBundleId:textApp firstLaunch:YES];
            [self.selectedApps addObject:textApp];
            [self.collectionView reloadData];
        }
    });
'''
if marker not in s:
    raise SystemExit('ViewController setup marker not found')
s = s.replace(marker, inject, 1)
vc.write_text(s)

with info.open('rb') as f:
    pl = plistlib.load(f)
pl['CFBundleIdentifier'] = 'local.pavel.WearMemoryTextKeeper'
pl['CFBundleDisplayName'] = 'Text Keeper'
pl['CFBundleName'] = 'Text Keeper'
pl['CFBundleVersion'] = '1.0'
pl['CFBundleShortVersionString'] = '1.0'
pl['MinimumOSVersion'] = '15.0'
with info.open('wb') as f:
    plistlib.dump(pl, f, fmt=plistlib.FMT_XML, sort_keys=False)

m = make.read_text()
# Keep the upstream application executable name so the source and Makefile remain coherent.
m = m.replace('TARGET := iphone:clang:16.5:15.0', 'TARGET := iphone:clang:16.5:15.0')
make.write_text(m)
PY

cd "$PROJ"
make clean
make package FINALPACKAGE=1

PKG=$(find packages -maxdepth 1 -type f \( -name '*.ipa' -o -name '*.tipa' \) | head -1)
test -n "$PKG"
OUT=/tmp/WearMemory_Text_Keeper_FrontBoard_TrollStore_iOS15.tipa
cp "$PKG" "$OUT"

# Verify the package itself rather than trusting a successful compile.
unzip -t "$OUT"
APP_PATH='Payload/ImmortalizerTS.app/'
unzip -Z1 "$OUT" | grep -Fx "${APP_PATH}Info.plist"
unzip -p "$OUT" "${APP_PATH}Info.plist" > "$WORK/Info.plist"
plutil -lint "$WORK/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WORK/Info.plist" | grep -Fx 'local.pavel.WearMemoryTextKeeper'
/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$WORK/Info.plist" | grep -Fx 'Text Keeper'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$WORK/Info.plist" | grep -Fx '15.0'

# The entitlement set must include the exact FrontBoard/RunningBoard capabilities
# used by the upstream foreground-scene implementation.
EXE_NAME=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$WORK/Info.plist")
unzip -p "$OUT" "${APP_PATH}${EXE_NAME}" > "$WORK/TextKeeper"
chmod +x "$WORK/TextKeeper"
file "$WORK/TextKeeper" | grep -q 'arm64'
ldid -e "$WORK/TextKeeper" > "$WORK/entitlements.plist"
plutil -lint "$WORK/entitlements.plist"
/usr/libexec/PlistBuddy -c 'Print :com.apple.frontboard.launchapplications' "$WORK/entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.launchprocess' "$WORK/entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.targetidentities' "$WORK/entitlements.plist" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :platform-application' "$WORK/entitlements.plist" | grep -Fx 'true'

strings "$WORK/TextKeeper" | grep -Fq 'local.pavel.WearMemoryText'

cp "$PROJ/LICENSE" /tmp/ImmortalizerTS_GPLv3_LICENSE.txt
cp "$WORK/IMMORTALIZERTS_UPSTREAM_COMMIT.txt" /tmp/ImmortalizerTS_UPSTREAM_COMMIT.txt
shasum -a 256 "$OUT" | tee "$OUT.sha256"
ls -lh "$OUT"
