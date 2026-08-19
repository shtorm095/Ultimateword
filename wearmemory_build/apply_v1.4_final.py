#!/usr/bin/env python3
import base64, zlib, pathlib, sys, hashlib
root = pathlib.Path(sys.argv[1])
base = pathlib.Path(__file__).resolve().parent

def restore(prefix, count, out_name, expected_sha256):
    encoded = ''.join((base / f'{prefix}.{i}').read_text().strip() for i in range(count))
    data = zlib.decompress(base64.b64decode(encoded))
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise SystemExit(f'{out_name}: SHA256 mismatch {digest}')
    (root / out_name).write_bytes(data)
    print(f'{out_name}: {digest}')

restore('final_appmodel2', 2, 'AppModel.swift', 'c5da18e9309a92ede6e670f3706909f289668a5576d538ba6396d61bb79fda26')
restore('final_content', 5, 'ContentView.swift', 'a6da585aa4d72d8522f36f7fabd8df1e840934e14e606548cf0749ae3c35f68d')
restore('final_audio', 3, 'AudioBufferManager.swift', '5b1c253e16f17723132406674bd665078473126dafeb94e1ec022b2fe7df3c4b')
restore('final_info', 1, 'Info.plist', 'f1f207571a73e2d95535a64b4d68de360a0631d3554e7bedc4a58608b1c8396c')

sync_encoded = ''.join((base / f'v14_sync0.{i}').read_text().strip() for i in range(4))
sync_encoded += ''.join((base / f'v14_sync.{i}').read_text().strip() for i in range(1, 5))
sync_data = zlib.decompress(base64.b64decode(sync_encoded))
sync_digest = hashlib.sha256(sync_data).hexdigest()
if sync_digest != '9f83111a71c1405cb41170624050dafec4ee299f92fe8ca299880bbea4dc9457':
    raise SystemExit(f'GoogleDriveSync.swift: SHA256 mismatch {sync_digest}')
(root / 'GoogleDriveSync.swift').write_bytes(sync_data)
print(f'GoogleDriveSync.swift: {sync_digest}')
