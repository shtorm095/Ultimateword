#import <Foundation/Foundation.h>
#import <spawn.h>
#import <sys/stat.h>
#import <sys/wait.h>
#import <unistd.h>

extern char **environ;

static NSString *const TargetBundleID = @"local.pavel.WearMemoryText";
static NSString *const ClassicTrollStoreID = @"com.opa334.TrollStore";
static NSString *const LiteTrollStoreID = @"com.opa334.TrollStoreLite";
static const unsigned long long BaseModelSize = 147951465ULL;
static const unsigned long long SmallModelSize = 190085487ULL;
static const unsigned long long PayloadExecutableSize = 2671760ULL;
static NSString *const BackupDir = @"/private/var/mobile/Library/WearMemoryTextPatch127Backup";

static NSString *FindApp(NSString *bundleID) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *root = @"/private/var/containers/Bundle/Application";
    for (NSString *container in [fm contentsOfDirectoryAtPath:root error:nil]) {
        NSString *containerPath = [root stringByAppendingPathComponent:container];
        for (NSString *item in [fm contentsOfDirectoryAtPath:containerPath error:nil]) {
            if (![item.pathExtension.lowercaseString isEqualToString:@"app"]) continue;
            NSString *appPath = [containerPath stringByAppendingPathComponent:item];
            NSDictionary *info = [NSDictionary dictionaryWithContentsOfFile:[appPath stringByAppendingPathComponent:@"Info.plist"]];
            if ([info[@"CFBundleIdentifier"] isEqualToString:bundleID]) return appPath;
        }
    }
    return nil;
}

static unsigned long long FileSize(NSString *path) {
    return [[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil][NSFileSize] unsignedLongLongValue];
}

static BOOL VersionAtLeast21(NSString *version) {
    NSArray<NSString *> *p = [version componentsSeparatedByString:@"."];
    NSInteger major = p.count > 0 ? p[0].integerValue : 0;
    NSInteger minor = p.count > 1 ? p[1].integerValue : 0;
    return major > 2 || (major == 2 && minor >= 1);
}

static BOOL CopyReplacing(NSString *source, NSString *dest) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *tmp = [dest stringByAppendingString:@".wm127tmp"];
    [fm removeItemAtPath:tmp error:nil];
    NSError *error = nil;
    if (![fm copyItemAtPath:source toPath:tmp error:&error]) return NO;
    [fm removeItemAtPath:dest error:nil];
    return [fm moveItemAtPath:tmp toPath:dest error:&error];
}

static BOOL DecodePayload(NSString *encoded, NSString *decoded) {
    NSMutableData *data = [[NSData dataWithContentsOfFile:encoded options:NSDataReadingMappedIfSafe error:nil] mutableCopy];
    if (!data || data.length != PayloadExecutableSize) return NO;
    uint8_t *bytes = data.mutableBytes;
    for (NSUInteger i = 0; i < data.length; i++) bytes[i] ^= 0xA5;
    return [data writeToFile:decoded options:NSDataWritingAtomic error:nil];
}

static BOOL EnsureBackup(NSString *appPath) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *bExec = [BackupDir stringByAppendingPathComponent:@"WearMemoryText"];
    NSString *bInfo = [BackupDir stringByAppendingPathComponent:@"Info.plist"];
    NSString *bCode = [BackupDir stringByAppendingPathComponent:@"CodeResources"];
    if ([fm fileExistsAtPath:bExec] && [fm fileExistsAtPath:bInfo] && [fm fileExistsAtPath:bCode]) return YES;
    [fm removeItemAtPath:BackupDir error:nil];
    if (![fm createDirectoryAtPath:BackupDir withIntermediateDirectories:YES attributes:nil error:nil]) return NO;
    if (![fm copyItemAtPath:[appPath stringByAppendingPathComponent:@"WearMemoryText"] toPath:bExec error:nil]) return NO;
    if (![fm copyItemAtPath:[appPath stringByAppendingPathComponent:@"Info.plist"] toPath:bInfo error:nil]) return NO;
    if (![fm copyItemAtPath:[appPath stringByAppendingPathComponent:@"_CodeSignature/CodeResources"] toPath:bCode error:nil]) return NO;
    return YES;
}

static void RestoreBackup(NSString *appPath, NSString *activeMarker, NSString *inactiveMarker) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *exec = [appPath stringByAppendingPathComponent:@"WearMemoryText"];
    NSString *info = [appPath stringByAppendingPathComponent:@"Info.plist"];
    NSString *code = [appPath stringByAppendingPathComponent:@"_CodeSignature/CodeResources"];
    CopyReplacing([BackupDir stringByAppendingPathComponent:@"WearMemoryText"], exec);
    CopyReplacing([BackupDir stringByAppendingPathComponent:@"Info.plist"], info);
    CopyReplacing([BackupDir stringByAppendingPathComponent:@"CodeResources"], code);
    chmod(exec.fileSystemRepresentation, 0755); chown(exec.fileSystemRepresentation, 33, 33);
    chmod(info.fileSystemRepresentation, 0644); chown(info.fileSystemRepresentation, 33, 33);
    chmod(code.fileSystemRepresentation, 0644); chown(code.fileSystemRepresentation, 33, 33);
    [[NSData data] writeToFile:[appPath.stringByDeletingLastPathComponent stringByAppendingPathComponent:activeMarker] atomically:YES];
    [fm removeItemAtPath:[appPath.stringByDeletingLastPathComponent stringByAppendingPathComponent:inactiveMarker] error:nil];
}

static int Run(NSString *path, NSArray<NSString *> *args) {
    NSMutableArray<NSString *> *all = [NSMutableArray arrayWithObject:path];
    [all addObjectsFromArray:args ?: @[]];
    char **argv = calloc(all.count + 1, sizeof(char *));
    for (NSUInteger i = 0; i < all.count; i++) argv[i] = strdup(all[i].UTF8String);
    pid_t pid = 0;
    int r = posix_spawn(&pid, path.fileSystemRepresentation, NULL, NULL, argv, environ);
    for (NSUInteger i = 0; i < all.count; i++) free(argv[i]);
    free(argv);
    if (r != 0) return 200 + r;
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) return 250;
    if (!WIFEXITED(status)) return 251;
    return WEXITSTATUS(status);
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        if (getuid() != 0) return 19;
        if (argc < 3 || strcmp(argv[1], "apply") != 0) return 18;
        NSString *patcherBundle = [NSString stringWithUTF8String:argv[2]];
        NSFileManager *fm = NSFileManager.defaultManager;

        NSString *target = FindApp(TargetBundleID);
        if (!target) return 20;
        NSString *container = target.stringByDeletingLastPathComponent;
        BOOL classicOwned = [fm fileExistsAtPath:[container stringByAppendingPathComponent:@"_TrollStore"]];
        BOOL liteOwned = [fm fileExistsAtPath:[container stringByAppendingPathComponent:@"_TrollStoreLite"]];
        if (!classicOwned && !liteOwned) return 21;

        if (FileSize([target stringByAppendingPathComponent:@"ggml-base.bin"]) != BaseModelSize ||
            FileSize([target stringByAppendingPathComponent:@"ggml-small-q5_1.bin"]) != SmallModelSize) return 22;

        NSString *encoded = [patcherBundle stringByAppendingPathComponent:@"target-executable.xor"];
        if (FileSize(encoded) != PayloadExecutableSize) return 23;

        NSString *tsBundleID = classicOwned ? ClassicTrollStoreID : LiteTrollStoreID;
        NSString *tsApp = FindApp(tsBundleID);
        if (!tsApp) return 24;
        NSDictionary *tsInfo = [NSDictionary dictionaryWithContentsOfFile:[tsApp stringByAppendingPathComponent:@"Info.plist"]];
        NSString *tsVersion = tsInfo[@"CFBundleVersion"] ?: tsInfo[@"CFBundleShortVersionString"];
        if (!VersionAtLeast21(tsVersion)) return 25;
        NSString *tsHelper = [tsApp stringByAppendingPathComponent:@"trollstorehelper"];
        if (![fm isExecutableFileAtPath:tsHelper]) return 24;

        if (!EnsureBackup(target)) return 26;

        NSString *decoded = [@"/private/var/tmp" stringByAppendingPathComponent:[NSString stringWithFormat:@"wm127-%@", NSUUID.UUID.UUIDString]];
        if (!DecodePayload(encoded, decoded)) return 23;
        chmod(decoded.fileSystemRepresentation, 0755);

        NSString *targetExec = [target stringByAppendingPathComponent:@"WearMemoryText"];
        if (!CopyReplacing(decoded, targetExec)) {
            [fm removeItemAtPath:decoded error:nil];
            RestoreBackup(target, classicOwned ? @"_TrollStore" : @"_TrollStoreLite", classicOwned ? @"_TrollStoreLite" : @"_TrollStore");
            return 27;
        }
        [fm removeItemAtPath:decoded error:nil];
        chmod(targetExec.fileSystemRepresentation, 0755); chown(targetExec.fileSystemRepresentation, 33, 33);

        NSString *infoPath = [target stringByAppendingPathComponent:@"Info.plist"];
        NSMutableDictionary *info = [[NSDictionary dictionaryWithContentsOfFile:infoPath] mutableCopy];
        if (!info) { RestoreBackup(target, classicOwned ? @"_TrollStore" : @"_TrollStoreLite", classicOwned ? @"_TrollStoreLite" : @"_TrollStore"); return 27; }
        info[@"CFBundleShortVersionString"] = @"1.2.7";
        info[@"CFBundleVersion"] = @"27";
        NSMutableArray *modes = [info[@"UIBackgroundModes"] mutableCopy];
        if (modes) {
            [modes removeObject:@"audio"];
            if (modes.count) info[@"UIBackgroundModes"] = modes;
            else [info removeObjectForKey:@"UIBackgroundModes"];
        }
        if (![info writeToFile:infoPath atomically:YES]) { RestoreBackup(target, classicOwned ? @"_TrollStore" : @"_TrollStoreLite", classicOwned ? @"_TrollStoreLite" : @"_TrollStore"); return 27; }
        chmod(infoPath.fileSystemRepresentation, 0644); chown(infoPath.fileSystemRepresentation, 33, 33);

        NSString *activeMarker = classicOwned ? @"_TrollStore" : @"_TrollStoreLite";
        NSString *inactiveMarker = classicOwned ? @"_TrollStoreLite" : @"_TrollStore";
        [[NSData data] writeToFile:[container stringByAppendingPathComponent:inactiveMarker] atomically:YES];
        [fm removeItemAtPath:[container stringByAppendingPathComponent:activeMarker] error:nil];

        int transfer = Run(tsHelper, @[@"transfer-apps"]);
        if (transfer != 0) {
            NSString *current = FindApp(TargetBundleID) ?: target;
            RestoreBackup(current, activeMarker, inactiveMarker);
            return 28;
        }

        NSString *patched = FindApp(TargetBundleID);
        if (!patched) return 29;
        NSDictionary *patchedInfo = [NSDictionary dictionaryWithContentsOfFile:[patched stringByAppendingPathComponent:@"Info.plist"]];
        BOOL versionOK = [patchedInfo[@"CFBundleShortVersionString"] isEqualToString:@"1.2.7"] && [patchedInfo[@"CFBundleVersion"] isEqualToString:@"27"];
        BOOL noAudioMode = ![patchedInfo[@"UIBackgroundModes"] containsObject:@"audio"];
        BOOL modelsOK = FileSize([patched stringByAppendingPathComponent:@"ggml-base.bin"]) == BaseModelSize && FileSize([patched stringByAppendingPathComponent:@"ggml-small-q5_1.bin"]) == SmallModelSize;
        BOOL execOK = FileSize([patched stringByAppendingPathComponent:@"WearMemoryText"]) == PayloadExecutableSize;
        BOOL markerOK = [fm fileExistsAtPath:[patched.stringByDeletingLastPathComponent stringByAppendingPathComponent:activeMarker]];
        if (!versionOK || !noAudioMode || !modelsOK || !execOK || !markerOK) {
            RestoreBackup(patched, activeMarker, inactiveMarker);
            return 29;
        }
        return 0;
    }
}
