#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production.sh"
TEMP=/tmp/wearmemory-text-v122-build.sh

python3 - "$SOURCE" "$TEMP" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])

needle = 'python3 "$ROOT/wearmemory_text_v121/whisper_production_patch.py"\n'
if needle not in source:
    raise SystemExit('Whisper production patch call not found')
source = source.replace(
    needle,
    needle + 'python3 "$ROOT/wearmemory_text_v121/german_confidence_patch.py"\n',
    1,
)

source = source.replace("grep -Fx '1.2.1'", "grep -Fx '1.2.2'")
source = source.replace("grep -Fx '21'", "grep -Fx '22'")
source = source.replace(
    "grep -Fq 'Whisper Base · Deutsch · offline' \"$SRC/TextProcessor.swift\"",
    "grep -Fq 'Whisper · DE Elektro' \"$SRC/TextProcessor.swift\"",
)
source = source.replace(
    "grep -Fq 'offline · CPU NoBLAS' \"$SRC/ContentView.swift\"",
    "grep -Fq 'DE Elektro · Score' \"$SRC/ContentView.swift\"",
)

old_ipa = 'WearMemoryText_v1.2.1b21_WhisperBase_CPU_NoBLAS_iOS15'
new_ipa = 'WearMemoryText_v1.2.2b22_DEElektro_Confidence_CPU_NoBLAS_iOS15'
source = source.replace(old_ipa, new_ipa)
source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.2_Source.zip')

verification_marker = "grep -Fq 'params.temperature_inc = \"0.0f\"' \"$SRC/WMWhisperProductionBridge.mm\"\n"
# Existing script uses source-code text without escaped quotes in this line; append by a safer nearby marker instead.
near = "grep -Fq 'params.temperature_inc = 0.0f' \"$SRC/WMWhisperProductionBridge.mm\"\n"
if near not in source:
    raise SystemExit('Whisper parameter verification marker not found')
extra = near + "grep -Fq 'params.initial_prompt = ' \"$SRC/WMWhisperProductionBridge.mm\"\n" \
    + "grep -Fq 'whisper_full_get_token_p' \"$SRC/WMWhisperProductionBridge.mm\"\n" \
    + "grep -Fq 'GermanTranscriptNormalizer.normalize' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'lastWhisperConfidence' \"$SRC/TextProcessor.swift\"\n" \
    + "grep -Fq 'whisperConfidenceMethod' \"$SRC/TextProcessor.swift\"\n" \
    + "test -f \"$SRC/GermanTranscriptNormalizer.swift\"\n"
source = source.replace(near, extra, 1)

out.write_text(source)
PY

bash "$TEMP"
