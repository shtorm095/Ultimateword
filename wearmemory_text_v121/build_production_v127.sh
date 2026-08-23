#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production_v124.sh"
TEMP=/tmp/wearmemory-text-v127-wrapper.sh

python3 - "$SOURCE" "$TEMP" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])

old_patch = '''    + 'python3 "$ROOT/wearmemory_text_v121/german_confidence_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/dual_pass_base_small_patch.py"\\n',
'''
new_patch = '''    + 'python3 "$ROOT/wearmemory_text_v121/german_confidence_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/dual_pass_base_small_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/background_processing_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/no_file_deadline_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/delete_successful_audio_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/small_quality_gate_patch.py"\\n'
    + 'python3 "$ROOT/wearmemory_text_v121/runningboard_background_patch.py"\\n',
'''
if old_patch not in source:
    raise SystemExit('v1.2.4 patch chain marker not found')
source = source.replace(old_patch, new_patch, 1)

source = source.replace("grep -Fx '1.2.1'\", \"grep -Fx '1.2.4'", "grep -Fx '1.2.1'\", \"grep -Fx '1.2.7'")
source = source.replace("grep -Fx '21'\", \"grep -Fx '24'", "grep -Fx '21'\", \"grep -Fx '27'")
source = source.replace(
    "new_ipa = 'WearMemoryText_v1.2.4b24_Base_SmallQ5_1_DualPass_DEElektro_iOS15'",
    "new_ipa = 'WearMemoryText_v1.2.7b27_Base_SmallQ5_1_RunningBoard_9MinuteWatchdog_DEElektro_iOS15'",
)
source = source.replace(
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.4_Source.zip')",
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.7_Source.zip')",
)

out.write_text(source)
PY

bash "$TEMP"

SRC=/tmp/wmtext121-src/WearMemoryText
APP=/tmp/wmtext121-derived/Build/Products/Release-iphoneos/WearMemoryText.app
IPA=/tmp/WearMemoryText_v1.2.7b27_Base_SmallQ5_1_RunningBoard_9MinuteWatchdog_DEElektro_iOS15.ipa

test -f "$SRC/WMRunningBoardKeeper.m"
test -f "$SRC/WMRunningBoardKeeper.h"
grep -Fq 'RBSLegacyAttribute' "$SRC/WMRunningBoardKeeper.m"
grep -Fq 'PreventTaskSuspend' "$SRC/WMRunningBoardKeeper.m"
grep -Fq 'processor.$pendingCount' "$SRC/TextAppModel.swift"
grep -Fq 'RunningBoard: активен' "$SRC/BackgroundExecutionKeeper.swift"
grep -Fq '"Фон"' "$SRC/ContentView.swift"
! /usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes' "$SRC/Info.plist" >/tmp/wm127-bg-modes.txt 2>&1
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.primitiveattribute' "$SRC/WearMemoryText.entitlements" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.assertions.frontboard' "$SRC/WearMemoryText.entitlements" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.process-state' "$SRC/WearMemoryText.entitlements" | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :platform-application' "$SRC/WearMemoryText.entitlements" | grep -Fx 'true'

test -d "$APP"
test -f "$IPA"
file "$APP/WearMemoryText" | grep -q 'arm64'
strings "$APP/WearMemoryText" > /tmp/wm127-strings.txt
grep -Fq 'RunningBoardServices.framework/RunningBoardServices' /tmp/wm127-strings.txt
grep -Fq 'RBSLegacyAttribute' /tmp/wm127-strings.txt

codesign -d --entitlements :- "$APP" > /tmp/wm127-entitlements.plist 2>/dev/null
plutil -lint /tmp/wm127-entitlements.plist
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.primitiveattribute' /tmp/wm127-entitlements.plist | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.assertions.frontboard' /tmp/wm127-entitlements.plist | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.process-state' /tmp/wm127-entitlements.plist | grep -Fx 'true'
/usr/libexec/PlistBuddy -c 'Print :platform-application' /tmp/wm127-entitlements.plist | grep -Fx 'true'

shasum -a 256 "$IPA"
