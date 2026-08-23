from pathlib import Path
import plistlib

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
keeper_m = app / 'WMRunningBoardKeeper.m'
info = app / 'Info.plist'
entitlements = app / 'WearMemoryText.entitlements'

for path in (keeper_m, info, entitlements):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# v1.2.8 follows the 1.2.7 RunningBoard implementation, but grants the
# entitlement used for long-lived BKS/RBS process assertions.  Keep the
# failure visible as domain/code/reason so the physical iOS 15 device gives
# an actionable error instead of a truncated NSError description.
m = keeper_m.read_text()
old = '''        NSError *error = nil;
        if (![assertion acquireWithError:&error]) {
            SetError(error ? error.description : @"RunningBoard acquire failed");
            return 14;
        }
'''
new = '''        NSError *error = nil;
        if (![assertion acquireWithError:&error]) {
            if (error) {
                NSString *reason = error.userInfo[NSLocalizedFailureReasonErrorKey];
                if (!reason.length) reason = error.localizedFailureReason;
                if (!reason.length) reason = error.localizedDescription;
                SetError([NSString stringWithFormat:@"domain=%@ code=%ld reason=%@",
                          error.domain ?: @"?", (long)error.code, reason ?: @"?"]);
            } else {
                SetError(@"RunningBoard acquire failed without NSError");
            }
            return 14;
        }
'''
if old not in m:
    raise SystemExit('RunningBoard acquire diagnostic marker not found')
m = m.replace(old, new, 1)
keeper_m.write_text(m)

with entitlements.open('rb') as f:
    ent = plistlib.load(f)
ent['com.apple.multitasking.unlimitedassertions'] = True
with entitlements.open('wb') as f:
    plistlib.dump(ent, f, fmt=plistlib.FMT_XML, sort_keys=False)

with info.open('rb') as f:
    plist = plistlib.load(f)
plist['CFBundleShortVersionString'] = '1.2.8'
plist['CFBundleVersion'] = '28'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.8: unlimited RunningBoard assertion entitlement + exact RBS diagnostics')
