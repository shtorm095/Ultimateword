#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production_v124.sh"
TEMP=/tmp/wearmemory-text-v129-wrapper.sh

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
    + 'python3 "$ROOT/wearmemory_text_v121/keeper_active_watchdog_patch.py"\\n',
'''
if old_patch not in source:
    raise SystemExit('v1.2.4 patch chain marker not found')
source = source.replace(old_patch, new_patch, 1)

source = source.replace("grep -Fx '1.2.1'\", \"grep -Fx '1.2.4'", "grep -Fx '1.2.1'\", \"grep -Fx '1.2.9'")
source = source.replace("grep -Fx '21'\", \"grep -Fx '24'", "grep -Fx '21'\", \"grep -Fx '29'")
source = source.replace(
    "new_ipa = 'WearMemoryText_v1.2.4b24_Base_SmallQ5_1_DualPass_DEElektro_iOS15'",
    "new_ipa = 'WearMemoryText_v1.2.9b29_Base_SmallQ5_1_TextKeeper_Active9MinuteWatchdog_DEElektro_iOS15'",
)
source = source.replace(
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.4_Source.zip')",
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.9_Source.zip')",
)

out.write_text(source)
PY

bash "$TEMP"

SRC=/tmp/wmtext121-src/WearMemoryText
APP=/tmp/wmtext121-derived/Build/Products/Release-iphoneos/WearMemoryText.app
IPA=/tmp/WearMemoryText_v1.2.9b29_Base_SmallQ5_1_TextKeeper_Active9MinuteWatchdog_DEElektro_iOS15.ipa

# Version / target.
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SRC/Info.plist" | grep -Fx '1.2.9'
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Info.plist" | grep -Fx '29'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
file "$APP/WearMemoryText" | grep -q 'arm64'

# FrontBoard Text Keeper is now the only background mechanism. The app itself
# must not carry the old silent-audio or experimental in-process RBS keeper.
! test -f "$SRC/WMRunningBoardKeeper.m"
! test -f "$SRC/WMRunningBoardKeeper.h"
! grep -R -Fq 'RBSLegacyAttribute' "$SRC"
! grep -R -Fq 'RunningBoard: активен' "$SRC"
! /usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes' "$SRC/Info.plist" >/tmp/wm129-bg-modes.txt 2>&1
! grep -Fq 'AVAudioEngine' "$SRC/BackgroundExecutionKeeper.swift"
grep -Fq 'func start() {}' "$SRC/BackgroundExecutionKeeper.swift"
grep -Fq 'if phase == .active { model.start() }' "$SRC/WearMemoryTextApp.swift"
! grep -Fq 'phase == .background { model.stopPolling() }' "$SRC/WearMemoryTextApp.swift"

# Real active-work watchdog is inside whisper.cpp/ggml. Verify source and final binary.
grep -Fq 'CLOCK_PROCESS_CPUTIME_ID' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'params.abort_callback = wm_whisper_abort_callback' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'params.abort_callback_user_data = &budget' "$SRC/WMWhisperProductionBridge.mm"
grep -Fq 'case activeTimeout' "$SRC/WhisperLocalRecognizer.swift"
grep -Fq 'activeBudgetSeconds: maxFileProcessingSeconds' "$SRC/TextProcessor.swift"
grep -Fq 'maxFileProcessingSeconds - baseTranscript.activeSeconds' "$SRC/TextProcessor.swift"
grep -Fq '9 минут работы' "$SRC/ContentView.swift"
strings "$APP/WearMemoryText" > /tmp/wm129-strings.txt
grep -Fq 'Aktives 9-Minuten-Limit erreicht' /tmp/wm129-strings.txt
grep -Fq 'Общий лимит активной обработки на iPod: 9 минут' /tmp/wm129-strings.txt

# The obsolete wall-clock watchdog must no longer dispatch markNeedsPC after 540 s.
python3 - "$SRC/TextProcessor.swift" <<'PY'
from pathlib import Path
import re, sys
s = Path(sys.argv[1]).read_text()
m = re.search(r'private func startFileDeadline\(item: TextQueueItem, sourceURL: URL\) \{(.*?)\n    \}', s, re.S)
if not m:
    raise SystemExit('startFileDeadline not found')
body = m.group(1)
if 'asyncAfter' in body or 'markNeedsPC' in body:
    raise SystemExit('obsolete wall-clock deadline still active')
PY

# Routing / quality contract must survive the watchdog rewrite.
grep -Fq 'baseTranscript.chunkTexts.count != smallTranscript.chunkTexts.count' "$SRC/TextProcessor.swift"
grep -Fq 'if !baseText.isEmpty && smallText.isEmpty' "$SRC/TextProcessor.swift"
grep -Fq 'let hasProcessingProblem = !warnings.isEmpty || cleanTextForRouting.isEmpty' "$SRC/TextProcessor.swift"
grep -Fq 'status: hasProcessingProblem ? "needs_pc" : "recognized_complete"' "$SRC/TextProcessor.swift"
grep -Fq 'self.onAudioReady?(sourceURL)' "$SRC/TextProcessor.swift"
grep -Fq 'try fm.removeItem(at: sourceURL)' "$SRC/TextProcessor.swift"
! grep -Fq 'let baseSummary =' "$SRC/TextProcessor.swift"

# Both models must be present and exactly the expected files.
test -f "$APP/ggml-base.bin"
test -f "$APP/ggml-small-q5_1.bin"
echo '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe  '"$APP/ggml-base.bin" | shasum -a 256 -c -
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$APP/ggml-small-q5_1.bin" | shasum -a 256 -c -

# No RBS-only entitlements in the signed app.
codesign -d --entitlements :- "$APP" > /tmp/wm129-entitlements.plist 2>/dev/null
plutil -lint /tmp/wm129-entitlements.plist
! /usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.primitiveattribute' /tmp/wm129-entitlements.plist >/dev/null 2>&1
! /usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.assertions.frontboard' /tmp/wm129-entitlements.plist >/dev/null 2>&1
! /usr/libexec/PlistBuddy -c 'Print :com.apple.multitasking.unlimitedassertions' /tmp/wm129-entitlements.plist >/dev/null 2>&1

test -f "$IPA"
unzip -t "$IPA"
shasum -a 256 "$IPA" | tee "$IPA.sha256"
