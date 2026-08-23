from pathlib import Path
import plistlib

root = Path('/tmp/wmtext121-src')
app = root / 'WearMemoryText'
keeper = app / 'BackgroundExecutionKeeper.swift'
model = app / 'TextAppModel.swift'
content = app / 'ContentView.swift'
bridge_h = app / 'WMWhisper-Bridging-Header.h'
info = app / 'Info.plist'
entitlements = app / 'WearMemoryText.entitlements'

for path in (keeper, model, content, bridge_h, info, entitlements):
    if not path.exists():
        raise SystemExit(f'missing {path}')

# Replace the silent-audio workaround with a direct RunningBoard assertion.
# This build is TrollStore-only: arbitrary private entitlements are intentional.
(app / 'WMRunningBoardKeeper.h').write_text(r'''#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

int wm_rbs_keepalive_start(void);
void wm_rbs_keepalive_stop(void);
int wm_rbs_keepalive_is_active(void);
const char * _Nullable wm_rbs_keepalive_last_error(void);

#ifdef __cplusplus
}
#endif
''')

(app / 'WMRunningBoardKeeper.m').write_text(r'''#import "WMRunningBoardKeeper.h"
#import <dlfcn.h>
#import <unistd.h>
#import <string.h>

// Private RunningBoardServices declarations used on iOS 15.
@interface RBSTarget : NSObject
+ (instancetype)targetWithPid:(pid_t)pid;
@end

@interface RBSAttribute : NSObject
@end

@interface RBSLegacyAttribute : RBSAttribute
+ (instancetype)attributeWithReason:(uint32_t)reason flags:(uint32_t)flags;
@end

@interface RBSAssertion : NSObject
- (instancetype)initWithExplanation:(NSString *)explanation target:(RBSTarget *)target attributes:(NSArray *)attributes;
- (BOOL)acquireWithError:(NSError **)error;
- (void)invalidate;
- (BOOL)isValid;
@end

static RBSAssertion *gAssertion = nil;
static void *gRunningBoardHandle = NULL;
static char gLastError[2048] = {0};

static void SetError(NSString *value) {
    const char *text = value.UTF8String ?: "unknown";
    strlcpy(gLastError, text, sizeof(gLastError));
}

int wm_rbs_keepalive_start(void) {
    @autoreleasepool {
        if (gAssertion) {
            if (![gAssertion respondsToSelector:@selector(isValid)] || gAssertion.isValid) {
                gLastError[0] = 0;
                return 0;
            }
            gAssertion = nil;
        }

        if (!gRunningBoardHandle) {
            gRunningBoardHandle = dlopen("/System/Library/PrivateFrameworks/RunningBoardServices.framework/RunningBoardServices", RTLD_NOW | RTLD_LOCAL);
            if (!gRunningBoardHandle) {
                SetError([NSString stringWithFormat:@"RunningBoardServices dlopen: %s", dlerror() ?: "unknown"]);
                return 10;
            }
        }

        Class targetClass = NSClassFromString(@"RBSTarget");
        Class legacyClass = NSClassFromString(@"RBSLegacyAttribute");
        Class assertionClass = NSClassFromString(@"RBSAssertion");
        if (!targetClass || !legacyClass || !assertionClass) {
            SetError(@"RunningBoard classes unavailable");
            return 11;
        }

        // iOS RunningBoard legacy flags:
        // 1 = PreventTaskSuspend, 2 = PreventTaskThrottleDown,
        // 8 = WantsForegroundResourcePriority.
        const uint32_t flags = 1u | 2u | 8u;
        // BackgroundUI = 7. This is the same legacy assertion reason used by
        // iOS background-keeping tools on the iOS 13-15 RunningBoard stack.
        const uint32_t reason = 7u;

        RBSTarget *target = [targetClass targetWithPid:getpid()];
        RBSLegacyAttribute *legacy = [legacyClass attributeWithReason:reason flags:flags];
        if (!target || !legacy) {
            SetError(@"RunningBoard target/attribute creation failed");
            return 12;
        }

        RBSAssertion *assertion = [[assertionClass alloc]
            initWithExplanation:@"WearMemory Text local Whisper Base -> Small"
            target:target
            attributes:@[legacy]];
        if (!assertion) {
            SetError(@"RunningBoard assertion creation failed");
            return 13;
        }

        NSError *error = nil;
        if (![assertion acquireWithError:&error]) {
            SetError(error ? error.description : @"RunningBoard acquire failed");
            return 14;
        }

        gAssertion = assertion;
        gLastError[0] = 0;
        return 0;
    }
}

void wm_rbs_keepalive_stop(void) {
    @autoreleasepool {
        if (gAssertion) {
            [gAssertion invalidate];
            gAssertion = nil;
        }
    }
}

int wm_rbs_keepalive_is_active(void) {
    @autoreleasepool {
        if (!gAssertion) return 0;
        if ([gAssertion respondsToSelector:@selector(isValid)]) return gAssertion.isValid ? 1 : 0;
        return 1;
    }
}

const char *wm_rbs_keepalive_last_error(void) {
    return gLastError[0] ? gLastError : NULL;
}
''')

keeper.write_text(r'''import Foundation

/// TrollStore-only background execution keeper.
///
/// Unlike the previous silent-audio workaround, this keeps a real
/// RunningBoard PreventTaskSuspend assertion while the Text queue is non-empty.
final class BackgroundExecutionKeeper {
    var onStatus: ((String) -> Void)?
    private var requested = false

    func start() {
        DispatchQueue.main.async { [weak self] in
            self?.startOnMain()
        }
    }

    func stop() {
        DispatchQueue.main.async { [weak self] in
            self?.stopOnMain()
        }
    }

    private func startOnMain() {
        guard !requested || wm_rbs_keepalive_is_active() == 0 else { return }
        let code = wm_rbs_keepalive_start()
        if code == 0, wm_rbs_keepalive_is_active() != 0 {
            requested = true
            onStatus?("RunningBoard: активен")
            return
        }

        requested = false
        if let value = wm_rbs_keepalive_last_error() {
            onStatus?("RBS ошибка \(code): \(String(cString: value))")
        } else {
            onStatus?("RBS ошибка \(code)")
        }
    }

    private func stopOnMain() {
        wm_rbs_keepalive_stop()
        requested = false
        onStatus?("RunningBoard: ожидание")
    }

    deinit {
        wm_rbs_keepalive_stop()
    }
}
''')

h = bridge_h.read_text()
if '#import "WMRunningBoardKeeper.h"' not in h:
    if not h.endswith('\n'):
        h += '\n'
    h += '#import "WMRunningBoardKeeper.h"\n'
bridge_h.write_text(h)

m = model.read_text()
if '@Published private(set) var journalFiles: [URL] = []\n' not in m:
    raise SystemExit('TextAppModel published marker not found')
m = m.replace(
    '@Published private(set) var journalFiles: [URL] = []\n',
    '@Published private(set) var journalFiles: [URL] = []\n    @Published private(set) var backgroundStatus = "RunningBoard: ожидание"\n',
    1,
)

old_subscription = '''        // Start the background-audio keep-alive as soon as local Whisper starts,
        // while the app is still in the foreground. This avoids a race when the
        // user locks the screen or switches apps during recognition.
        processor.$isProcessing
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] processing in
                if processing { self?.backgroundExecution.start() }
                else { self?.backgroundExecution.stop() }
            }
            .store(in: &cancellables)
'''
new_subscription = '''        backgroundExecution.onStatus = { [weak self] value in
            DispatchQueue.main.async { self?.backgroundStatus = value }
        }

        // Keep RunningBoard active for the complete queue, not only one file.
        // This deliberately avoids the old false -> true gap between files,
        // where iOS could suspend Text before the next Whisper pass started.
        processor.$pendingCount
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] pending in
                if pending > 0 { self?.backgroundExecution.start() }
                else { self?.backgroundExecution.stop() }
            }
            .store(in: &cancellables)
'''
if old_subscription not in m:
    raise SystemExit('old background subscription not found')
m = m.replace(old_subscription, new_subscription, 1)
model.write_text(m)

c = content.read_text()
ui_marker = '                info("cpu", "Base → Small Q5_1", model.processor.lastWhisperConfidence.map { "DE Elektro · Score \\(Int(($0 * 100).rounded()))%" } ?? "2-pass · offline", .green)\n'
if ui_marker not in c:
    raise SystemExit('ContentView Whisper row marker not found')
ui_replacement = ui_marker + '                info("bolt.horizontal.circle.fill", "Фон", model.backgroundStatus, model.backgroundStatus.contains("активен") ? .green : (model.backgroundStatus.contains("ошибка") ? .red : .secondary))\n'
c = c.replace(ui_marker, ui_replacement, 1)
content.write_text(c)

with info.open('rb') as f:
    plist = plistlib.load(f)
# Silent audio mode is no longer used.
modes = [value for value in plist.get('UIBackgroundModes', []) if value != 'audio']
if modes:
    plist['UIBackgroundModes'] = modes
else:
    plist.pop('UIBackgroundModes', None)
plist['CFBundleShortVersionString'] = '1.2.7'
plist['CFBundleVersion'] = '27'
with info.open('wb') as f:
    plistlib.dump(plist, f, fmt=plistlib.FMT_XML, sort_keys=False)

with entitlements.open('rb') as f:
    ent = plistlib.load(f)
# Required by RunningBoard when an application originates legacy assertions.
ent['com.apple.runningboard.primitiveattribute'] = True
ent['com.apple.runningboard.assertions.frontboard'] = True
ent['com.apple.runningboard.process-state'] = True
# TrollStore/CoreTrust permits the private entitlement set. platform-application
# matches Apple's own frontboard-capable clients and avoids a policy mismatch.
ent['platform-application'] = True
with entitlements.open('wb') as f:
    plistlib.dump(ent, f, fmt=plistlib.FMT_XML, sort_keys=False)

print('patched WearMemory Text 1.2.7: RunningBoard PreventTaskSuspend background execution')
