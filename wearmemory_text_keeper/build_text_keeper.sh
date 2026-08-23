#!/bin/bash
set -euo pipefail

WORK=/tmp/wm-text-keeper
THEOS=/tmp/theos
rm -rf "$WORK" "$THEOS"
mkdir -p "$WORK"

# Build from the exact ImmortalizerTS revision whose FrontBoard scene mechanism
# has already been proven on the physical iPod.
git clone --depth 1 https://github.com/sergealagon/ImmortalizerTS.git "$WORK/ImmortalizerTS"
PROJ="$WORK/ImmortalizerTS"
UPSTREAM_SHA=$(git -C "$PROJ" rev-parse HEAD)
test "$UPSTREAM_SHA" = 'e2d89b9dbcde0e5b241e0a9e82d3ac4d2ee3e84b'
printf '%s\n' "$UPSTREAM_SHA" > "$WORK/IMMORTALIZERTS_UPSTREAM_COMMIT.txt"

# Theos + SDKs are required for the private FrontBoard/RunningBoard frameworks.
git clone --recursive --depth 1 https://github.com/theos/theos.git "$THEOS"
rm -rf "$THEOS/sdks"
git clone --depth 1 https://github.com/theos/sdks.git "$THEOS/sdks"
export THEOS

if ! command -v ldid >/dev/null 2>&1; then
  brew install ldid
fi
command -v ldid

python3 - "$PROJ" <<'PY'
from pathlib import Path
import plistlib, sys

p = Path(sys.argv[1])
vc = p / 'src/ViewController.m'
info = p / 'Resources/Info.plist'

s = vc.read_text()

# Minimal navigation: this build is dedicated to WearMemory Text only.
old_nav = '''- (void)setupNavigationBar {\n    self.title = @"Immortalizer";\n    \n    UIBarButtonItem *addButton = [[UIBarButtonItem alloc] \n                                 initWithBarButtonSystemItem:UIBarButtonSystemItemAdd \n                                 target:self \n                                 action:@selector(addButtonTapped)];\n    self.navigationItem.rightBarButtonItem = addButton;\n}\n'''
new_nav = '''- (void)setupNavigationBar {\n    self.title = @"Text Keeper";\n    self.navigationItem.rightBarButtonItem = nil;\n}\n'''
if old_nav not in s:
    raise SystemExit('navigation block not found')
s = s.replace(old_nav, new_nav, 1)

# Automatically locate and immortalize only WearMemory Text.
marker = '    [self setupCollectionView];\n'
inject = r'''    [self setupCollectionView];

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

# WearMemory Text is a multi-scene app. The upstream code asks the user to press
# "Launch Here". We already proved that path on-device, so v2 performs the exact
# same kill -> relaunch(firstLaunch:NO) transition automatically.
start_marker = '''            if (scenelayer && scenelayer.level != 10) {\n                /* normally, level is 0 in multi scene apps. we can't immortalize multiple scenes. only one created inside immortalizerts. */\n'''
end_marker = '''            } else {\n                /* single scene, proceed */\n                [self showToast:app.localizedName withDescription:@"Immortalized"];\n            }\n'''
start = s.find(start_marker)
if start < 0:
    raise SystemExit('multi-scene start marker not found')
end = s.find(end_marker, start)
if end < 0:
    raise SystemExit('multi-scene end marker not found')
end += len(end_marker)
auto_block = r'''            if (scenelayer && scenelayer.level != 10) {
                int pid = self.scenesByBundleId[bundleId].clientProcess.pid;
                [self killAppWithPid:pid withCompletion:^{
                    [self initializeNewSceneForBundleId:app firstLaunch:NO];
                }];
            } else {
                [self showToast:app.localizedName withDescription:@"Text Keeper активен"];
            }
'''
s = s[:start] + auto_block + s[end:]

# Verify source-level invariants before compiling.
for needle in (
    'self.title = @"Text Keeper"',
    'local.pavel.WearMemoryText',
    '[self killAppWithPid:pid withCompletion:',
    '[self initializeNewSceneForBundleId:app firstLaunch:NO]',
    'settings.foreground = YES',
    'settings.backgrounded = NO',
):
    if needle not in s:
        raise SystemExit(f'missing Keeper invariant: {needle}')
if 'actionWithTitle:@"Launch Here"' in s:
    raise SystemExit('manual Launch Here flow still present')
vc.write_text(s)

with info.open('rb') as f:
    pl = plistlib.load(f)
pl['CFBundleIdentifier'] = 'local.pavel.WearMemoryTextKeeper'
pl['CFBundleDisplayName'] = 'Text Keeper'
pl['CFBundleName'] = 'Text Keeper'
pl['CFBundleVersion'] = '2'
pl['CFBundleShortVersionString'] = '2.0'
pl['MinimumOSVersion'] = '15.0'
with info.open('wb') as f:
    plistlib.dump(pl, f, fmt=plistlib.FMT_XML, sort_keys=False)
PY

cd "$PROJ"
make clean
make package FINALPACKAGE=1

PKG=$(find packages -maxdepth 1 -type f \( -name '*.ipa' -o -name '*.tipa' \) | head -1)
test -n "$PKG"
OUT=/tmp/WearMemory_Text_Keeper_v2_Auto_FrontBoard_TrollStore_iOS15.tipa
cp "$PKG" "$OUT"

# Verify the actual packaged application, not only the source tree.
unzip -t "$OUT"
APP_PATH='Payload/ImmortalizerTS.app/'
unzip -Z1 "$OUT" | grep -Fx "${APP_PATH}Info.plist"
unzip -p "$OUT" "${APP_PATH}Info.plist" > "$WORK/Info.plist"
plutil -lint "$WORK/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WORK/Info.plist" | grep -Fx 'local.pavel.WearMemoryTextKeeper'
/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$WORK/Info.plist" | grep -Fx 'Text Keeper'
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$WORK/Info.plist" | grep -Fx '2.0'
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$WORK/Info.plist" | grep -Fx '2'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$WORK/Info.plist" | grep -Fx '15.0'

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

strings "$WORK/TextKeeper" > "$WORK/TextKeeper.strings"
grep -Fq 'local.pavel.WearMemoryText' "$WORK/TextKeeper.strings"
grep -Fq 'Text Keeper' "$WORK/TextKeeper.strings"
! grep -Fq 'Launch Here' "$WORK/TextKeeper.strings"

cp "$PROJ/LICENSE" /tmp/ImmortalizerTS_GPLv3_LICENSE.txt
cp "$WORK/IMMORTALIZERTS_UPSTREAM_COMMIT.txt" /tmp/ImmortalizerTS_UPSTREAM_COMMIT.txt
shasum -a 256 "$OUT" | tee "$OUT.sha256"
ls -lh "$OUT"
