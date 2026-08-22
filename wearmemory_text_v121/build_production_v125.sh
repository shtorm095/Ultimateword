#!/bin/bash
set -euo pipefail

ROOT="$GITHUB_WORKSPACE"
SOURCE="$ROOT/wearmemory_text_v121/build_production_v124.sh"
TEMP=/tmp/wearmemory-text-v125-wrapper.sh

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
    + 'python3 "$ROOT/wearmemory_text_v121/background_processing_patch.py"\\n',
'''
if old_patch not in source:
    raise SystemExit('v1.2.4 patch chain marker not found')
source = source.replace(old_patch, new_patch, 1)

source = source.replace("grep -Fx '1.2.1'\", \"grep -Fx '1.2.4'", "grep -Fx '1.2.1'\", \"grep -Fx '1.2.5'")
source = source.replace("grep -Fx '21'\", \"grep -Fx '24'", "grep -Fx '21'\", \"grep -Fx '25'")
source = source.replace(
    "new_ipa = 'WearMemoryText_v1.2.4b24_Base_SmallQ5_1_DualPass_DEElektro_iOS15'",
    "new_ipa = 'WearMemoryText_v1.2.5b25_Base_SmallQ5_1_DualPass_Background_DEElektro_iOS15'",
)
source = source.replace(
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.4_Source.zip')",
    "source = source.replace('WearMemoryText_v1.2.1_Source.zip', 'WearMemoryText_v1.2.5_Source.zip')",
)

verify_marker = '''    + "test -f \\\"$SRC/GermanTranscriptNormalizer.swift\\\"\\n"
'''
if verify_marker not in source:
    raise SystemExit('v1.2.4 verification tail marker not found')
verify_extra = verify_marker \
    + '''    + "test -f \\\"$SRC/BackgroundExecutionKeeper.swift\\\"\\n" \\
''' \
    + '''    + "grep -Fq 'processor.$isProcessing' \\\"$SRC/TextAppModel.swift\\\"\\n" \\
''' \
    + '''    + "grep -Fq 'UIBackgroundModes' \\\"$SRC/Info.plist\\\"\\n" \\
''' \
    + '''    + "grep -Fq '<string>audio</string>' \\\"$SRC/Info.plist\\\"\\n" \\
''' \
    + '''    + "! grep -Fq 'phase == .background { model.stopPolling() }' \\\"$SRC/WearMemoryTextApp.swift\\\"\\n"
'''
source = source.replace(verify_marker, verify_extra, 1)

out.write_text(source)
PY

bash "$TEMP"
