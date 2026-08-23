#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#import <spawn.h>
#import <sys/wait.h>
#import <unistd.h>

extern char **environ;
#ifndef POSIX_SPAWN_PERSONA_FLAGS_OVERRIDE
#define POSIX_SPAWN_PERSONA_FLAGS_OVERRIDE 1
#endif
extern int posix_spawnattr_set_persona_np(posix_spawnattr_t *attr, uid_t persona_id, uint32_t flags);
extern int posix_spawnattr_set_persona_uid_np(posix_spawnattr_t *attr, uid_t uid);
extern int posix_spawnattr_set_persona_gid_np(posix_spawnattr_t *attr, gid_t gid);

static int SpawnRoot(NSString *path, NSArray<NSString *> *arguments) {
    NSMutableArray<NSString *> *all = [NSMutableArray arrayWithObject:path];
    [all addObjectsFromArray:arguments ?: @[]];
    char **argv = calloc(all.count + 1, sizeof(char *));
    for (NSUInteger i = 0; i < all.count; i++) argv[i] = strdup(all[i].UTF8String);

    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    posix_spawnattr_set_persona_np(&attr, 99, POSIX_SPAWN_PERSONA_FLAGS_OVERRIDE);
    posix_spawnattr_set_persona_uid_np(&attr, 0);
    posix_spawnattr_set_persona_gid_np(&attr, 0);

    pid_t pid = 0;
    int spawnResult = posix_spawn(&pid, path.fileSystemRepresentation, NULL, &attr, argv, environ);
    posix_spawnattr_destroy(&attr);
    for (NSUInteger i = 0; i < all.count; i++) free(argv[i]);
    free(argv);
    if (spawnResult != 0) return 1000 + spawnResult;

    int status = 0;
    if (waitpid(pid, &status, 0) < 0) return 1100;
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 1200 + WTERMSIG(status);
    return 1300;
}

@interface PatchViewController : UIViewController
@property(nonatomic,strong) UILabel *statusLabel;
@property(nonatomic,strong) UIButton *installButton;
@end

@implementation PatchViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    UILabel *title = [UILabel new];
    title.translatesAutoresizingMaskIntoConstraints = NO;
    title.text = @"WearMemory Text 1.2.8 Patch v7";
    title.font = [UIFont boldSystemFontOfSize:24];
    title.numberOfLines = 0;
    title.textAlignment = NSTextAlignmentCenter;

    UILabel *info = [UILabel new];
    info.translatesAutoresizingMaskIntoConstraints = NO;
    info.text = @"Исправляет отказ RunningBoard assertion и добавляет точную RBS-диагностику. Base и Small Q5_1 остаются на устройстве. Перед установкой закрой Text.";
    info.font = [UIFont systemFontOfSize:16];
    info.numberOfLines = 0;
    info.textAlignment = NSTextAlignmentCenter;

    self.statusLabel = [UILabel new];
    self.statusLabel.translatesAutoresizingMaskIntoConstraints = NO;
    self.statusLabel.text = @"Готов к установке";
    self.statusLabel.font = [UIFont systemFontOfSize:15];
    self.statusLabel.numberOfLines = 0;
    self.statusLabel.textAlignment = NSTextAlignmentCenter;

    self.installButton = [UIButton buttonWithType:UIButtonTypeSystem];
    self.installButton.translatesAutoresizingMaskIntoConstraints = NO;
    self.installButton.titleLabel.font = [UIFont boldSystemFontOfSize:18];
    [self.installButton setTitle:@"Установить патч" forState:UIControlStateNormal];
    [self.installButton addTarget:self action:@selector(installPatch) forControlEvents:UIControlEventTouchUpInside];

    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:@[title, info, self.statusLabel, self.installButton]];
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 22;
    stack.alignment = UIStackViewAlignmentFill;
    [self.view addSubview:stack];

    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.leadingAnchor constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.trailingAnchor constant:-24],
        [stack.centerYAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.centerYAnchor],
        [self.installButton.heightAnchor constraintEqualToConstant:50]
    ]];
}

- (NSString *)messageForCode:(int)code {
    switch (code) {
        case 0: return @"Готово. Text обновлён до 1.2.8 build 28. Модели сохранены.";
        case 19: return @"Root helper не получил root-права. Патч не применён.";
        case 20: return @"Text не найден на устройстве.";
        case 21: return @"Text найден, но он не отмечен как приложение TrollStore.";
        case 22: return @"Модели Base/Small отсутствуют или имеют неожиданный размер. Патч не применён.";
        case 23: return @"Файл патча повреждён. Патч не применён.";
        case 24: return @"TrollStore или его helper не найден.";
        case 25: return @"Нужен TrollStore 2.1 или новее.";
        case 26: return @"Не удалось создать резервную копию. Патч не применён.";
        case 27: return @"Не удалось записать новый код. Выполнен откат.";
        case 28: return @"TrollStore не смог повторно подписать Text. Выполнен откат.";
        case 30: return @"После подписи Text не найден. Выполнен откат.";
        case 31: return @"После подписи не совпала версия Text. Выполнен откат.";
        case 32: return @"После подписи остался старый audio background mode. Выполнен откат.";
        case 33: return @"После подписи не прошла проверка моделей. Выполнен откат.";
        case 34: return @"После подписи не прошла проверка executable. Выполнен откат.";
        case 35: return @"После подписи не восстановился TrollStore marker. Выполнен откат.";
        case 1209: return @"Root helper остановлен iOS через SIGKILL. Патч не применён.";
        default: return [NSString stringWithFormat:@"Ошибка установки: %d", code];
    }
}

- (void)installPatch {
    self.installButton.enabled = NO;
    self.statusLabel.text = @"Устанавливаю…";
    NSString *helper = [[NSBundle mainBundle] pathForResource:@"patchhelper" ofType:nil];
    NSString *bundlePath = NSBundle.mainBundle.bundlePath;
    if (!helper) {
        self.statusLabel.text = @"patchhelper отсутствует";
        self.installButton.enabled = YES;
        return;
    }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        int result = SpawnRoot(helper, @[@"apply", bundlePath]);
        dispatch_async(dispatch_get_main_queue(), ^{
            self.statusLabel.text = [self messageForCode:result];
            self.installButton.enabled = YES;
        });
    });
}
@end

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [PatchViewController new];
    [self.window makeKeyAndVisible];
    return YES;
}
@end

int main(int argc, char * argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class));
    }
}
