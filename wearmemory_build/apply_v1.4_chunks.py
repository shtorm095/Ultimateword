#!/usr/bin/env python3
import base64, zlib, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
base = pathlib.Path(__file__).resolve().parent
sync = ''.join((base / f'v14_sync0.{i}').read_text().strip() for i in range(4))
sync += ''.join((base / f'v14_sync.{i}').read_text().strip() for i in range(1, 5))
patch = ''.join((base / f'v14_patch.{i}').read_text().strip() for i in range(3))
(root / 'GoogleDriveSync.swift').write_bytes(zlib.decompress(base64.b64decode(sync)))
patch_bytes = zlib.decompress(base64.b64decode(patch))
proc = subprocess.run(['patch', '-p0', '--forward', '--batch'], cwd=root.parent, input=patch_bytes, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print(proc.stdout.decode(errors='replace'))
if proc.returncode != 0:
    raise SystemExit(proc.returncode)
print('Applied WearMemory v1.4 OAuth/Drive changes')
