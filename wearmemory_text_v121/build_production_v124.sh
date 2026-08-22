#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production.sh"
TEMP=/tmp/wearmemory-text-v124-build.sh

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
    needle
    + 'python3 "$ROOT/wearmemory_text_v121/german_confidence_patch.py"\n'
    + 'python3 "$ROOT/wearmemory_text_v121/dual_pass_base_small_patch.py"\n',
    1,
)

source = source.replace("grep -Fx '1.2.1'", "grep -Fx '1.2.4'")
source = source.replace("grep -Fx '21'", "grep -Fx '24'")
source = source.replace(
    "grep -Fq 'WhisperLocalRecognizer.transcribe(url: sourceURL)' \"$SRC/TextProcessor.swift\"",
    "grep -Fq 'WhisperLocalRecognizer.transcribe(url: sourceURL, model: .base)' \"$SRC/TextProcessor.swift\"",
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
new_ipa = 'WearMemoryText_v1.2.4b24_Base_SmallQ5_1_DualPass_DEElektro_iOS15'
source = source.replace(old_ipa, new_ipa)
source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.4_Source.zip')

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
    + "test -f \"$SRC/GermanTranscriptNormalizer.swift\"\n"
source = source.replace(near, extra, 1)

base_model_block = '''MODEL=/tmp/ggml-base.bin
curl -L --fail --retry 5 --retry-delay 3 -o "$MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$MODEL" | shasum -c -
'''
if base_model_block not in source:
    raise SystemExit('Base model download block not found')
small_model_block = base_model_block + '''
SMALL_MODEL=/tmp/ggml-small-q5_1.bin
curl -L --fail --retry 5 --retry-delay 3 -o "$SMALL_MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$SMALL_MODEL" | shasum -a 256 -c -
'''
source = source.replace(base_model_block, small_model_block, 1)

base_copy_block = '''cp /tmp/ggml-base.bin "$APP/ggml-base.bin"
echo '465707469ff3a37a2b9b8d8f89f2f99de7299dac  '"$APP/ggml-base.bin" | shasum -c -
'''
if base_copy_block not in source:
    raise SystemExit('Base model copy block not found')
small_copy_block = base_copy_block + '''cp /tmp/ggml-small-q5_1.bin "$APP/ggml-small-q5_1.bin"
echo 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb  '"$APP/ggml-small-q5_1.bin" | shasum -a 256 -c -
'''
source = source.replace(base_copy_block, small_copy_block, 1)

out.write_text(source)
PY

bash "$TEMP"
