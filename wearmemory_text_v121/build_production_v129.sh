#!/bin/bash
set -euo pipefail
trap 'echo "WM129_FAIL line=$LINENO command=$BASH_COMMAND" >&2' ERR

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production.sh"
TEMP=/tmp/wearmemory-text-v129-build.sh

python3 - "$SOURCE" "$TEMP" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])

# Build 1.2.9 directly from the known 1.2.1 production baseline. Do not nest
# transformations through v1.2.4/v1.2.8 wrappers: exact generated checks are
# defined here so CI cannot silently validate an obsolete API.
needle = 'python3 "$ROOT/wearmemory_text_v121/whisper_production_patch.py"\n'
if needle not in source:
    raise SystemExit('Whisper production patch call not found')
source = source.replace(
    needle,
    needle
    + 'python3 "$ROOT/wearmemory_text_v121/german_confidence_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/dual_pass_base_small_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/background_processing_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/no_file_deadline_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/delete_successful_audio_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/small_quality_gate_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/keeper_active_watchdog_patch.py"\n',
    1,
)

source = source.replace("grep -Fx '1.2.1'", "grep -Fx '1.2.9'")
source = source.replace("grep -Fx '21'", "grep -Fx '29'")
source = source.replace(
    "grep -Fq 'WhisperLocalRecognizer.transcribe(url: sourceURL)' \"$SRC/TextProcessor.swift\"",
    "grep -Fq 'activeBudgetSeconds: maxFileProcessingSeconds' \"$SRC/TextProcessor.swift\"",
)
source = source.replace(
    "grep -Fq 'Whisper Base · Deutsch · offline' \"$SRC/TextProcessor.swift\"",
    "grep -Fq 'Whisper Small Q5_1 · 2/2' \"$SRC/TextProcessor.swift\"",
)
source = source.replace(
    "grep -Fq 'offline · CPU NoBLAS' \"$SRC/ContentView.swift\"",
    "grep -Fq '2-pass · offline' \"$SRC/ContentView.swift\"",
)

old_ipa = 'WearMemoryText_v1.2.1b21_WhisperBase_CPU_NoBLAS_iOS15'
new_ipa = 'WearMemoryText_v1.2.9b29_Base_SmallQ5_1_TextKeeper_Active9MinuteWatchdog_DEElektro_iOS15'
if old_ipa not in source:
    raise SystemExit('baseline IPA name not found')
source = source.replace(old_ipa, new_ipa)
source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.9_Source.zip')

near = "grep -Fq 'params.temperature_inc = 0.0f' \"$SRC/WMWhisperProductionBridge.mm\"\n"
if near not in source:
    raise SystemExit('Whisper parameter verification marker not found')
extra = near \
    + "grep -Fq 'params.initial_prompt = ' \"$SRC/WMWhisperProductionBridge.mm\"\n" \
    + "grep -Fq 'GermanTranscriptNormalizer.normalize' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'lastWhisperConfidence' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'model: .base' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'model: .smallQ5_1' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'base->small-q5_1' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'ggml-small-q5_1' \"$SRC/WhisperLocalRecognizer.swift\"\n" \
    + "grep -Fq 'params.abort_callback = wm_whisper_abort_callback' \"$SRC/WMWhisperProductionBridge.mm\"\n" \
    + "grep -Fq 'CLOCK_PROCESS_CPUTIME_ID' \"$SRC/WMWhisperProductionBridge.mm\"\n" \
    + "test -f \"$SRC/GermanTranscriptNormalizer.swift\"\n"
source = source.replace(near, extra, 1)

base_model_block = '''MODEL=/tmp/ggml-base.bin
curl -L --fail --retry 5 --retry-delay 3 -o "$MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$MODEL" | shasum -c -
'''
if base_model_block not in source:
    raise SystemExit('Base model download block not found')
source = source.replace(base_model_block, base_model_block + '''
SMALL_MODEL=/tmp/ggml-small-q5_1.bin
curl -L --fail --retry 5 --retry-delay 3 -o "$SMALL_MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$SMALL_MODEL" | shasum -a 256 -c -
''', 1)

base_copy_block = '''cp /tmp/ggml-base.bin "$APP/ggml-base.bin"
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$APP/ggml-base.bin" | shasum -c -
'''
if base_copy_block not in source:
    raise SystemExit('Base model copy block not found')
source = source.replace(base_copy_block, base_copy_block + '''cp /tmp/ggml-small-q5_1.bin "$APP/ggml-small-q5_1.bin"
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$APP/ggml-small-q5_1.bin" | shasum -a 256 -c -
''', 1)

# Make a failing generated command visible in CI logs.
source = source.replace('set -euo pipefail\n', 'set -euo pipefail\ntrap \'echo "WM129_GENERATED_FAIL line=$LINENO command=$BASH_COMMAND" >&2\' ERR\n', 1)
out.write_text(source)
PY

bash "$TEMP"

SRC=/tmp/wmtext121-src/WearMemoryText
APP=/tmp/wmtext121-derived/Build/Products/Release-iphoneos/WearMemoryText.app
IPA=/tmp/WearMemoryText_v1.2.9b29_Base_SmallQ5_1_TextKeeper_Active9MinuteWatchdog_DEElektro_iOS15.ipa

/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SRC/Info.plist" | grep -Fx '1.2.9'
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SRC/Info.plist" | grep -Fx '29'
/usr/libexec/PlistBuddy -c 'Print :MinimumOSVersion' "$APP/Info.plist" | grep -Fx '15.0'
file "$APP/WearMemoryText" | grep -q 'arm64'

# Text Keeper/FrontBoard is the sole background mechanism.
! test -f "$SRC/WMRunningBoardKeeper.m"
! test -f "$SRC/WMRunningBoardKeeper.h"
! grep -R -Fq 'RBSLegacyAttribute' "$SRC"
! grep -R -Fq 'RunningBoard: активен' "$SRC"
! /usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes' "$SRC/Info.plist" >/tmp/wm129-bg-modes.txt 2>&1
! grep -Fq 'AVAudioEngine' "$SRC/BackgroundExecutionKeeper.swift"
grep -Fq 'func start() {}' "$SRC/BackgroundExecutionKeeper.swift"
grep -Fq 'if phase == .active { model.start() }' "$SRC/WearMemoryTextApp.swift"
! grep -Fq 'phase == .background { model.stopPolling() }' "$SRC/WearMemoryTextApp.swift"

# 540 seconds of cumulative process CPU time across Base + Small.
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

python3 - "$SRC/TextProcessor.swift" <<'PY'
from pathlib import Path
import re, sys
s = Path(sys.argv[1]).read_text()
m = re.search(r'private func startFileDeadline\(item: TextQueueItem, sourceURL: URL\) \{(.*?)\n    \}', s, re.S)
if not m:
    raise SystemExit('startFileDeadline not found')
if 'asyncAfter' in m.group(1) or 'markNeedsPC' in m.group(1):
    raise SystemExit('obsolete wall-clock deadline still active')
PY

# Existing routing contract remains intact.
grep -Fq 'baseTranscript.chunkTexts.count != smallTranscript.chunkTexts.count' "$SRC/TextProcessor.swift"
grep -Fq 'if !baseText.isEmpty && smallText.isEmpty' "$SRC/TextProcessor.swift"
grep -Fq 'let hasProcessingProblem = !warnings.isEmpty || cleanTextForRouting.isEmpty' "$SRC/TextProcessor.swift"
grep -Fq 'status: hasProcessingProblem ? "needs_pc" : "recognized_complete"' "$SRC/TextProcessor.swift"
grep -Fq 'self.onAudioReady?(sourceURL)' "$SRC/TextProcessor.swift"
grep -Fq 'try fm.removeItem(at: sourceURL)' "$SRC/TextProcessor.swift"
! grep -Fq 'let baseSummary =' "$SRC/TextProcessor.swift"

test -f "$APP/ggml-base.bin"
test -f "$APP/ggml-small-q5_1.bin"
echo '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe  '"$APP/ggml-base.bin" | shasum -a 256 -c -
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$APP/ggml-small-q5_1.bin" | shasum -a 256 -c -

codesign -d --entitlements :- "$APP" > /tmp/wm129-entitlements.plist 2>/dev/null
plutil -lint /tmp/wm129-entitlements.plist
! /usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.primitiveattribute' /tmp/wm129-entitlements.plist >/dev/null 2>&1
! /usr/libexec/PlistBuddy -c 'Print :com.apple.runningboard.assertions.frontboard' /tmp/wm129-entitlements.plist >/dev/null 2>&1
! /usr/libexec/PlistBuddy -c 'Print :com.apple.multitasking.unlimitedassertions' /tmp/wm129-entitlements.plist >/dev/null 2>&1

test -f "$IPA"
unzip -t "$IPA"
shasum -a 256 "$IPA" | tee "$IPA.sha256"
