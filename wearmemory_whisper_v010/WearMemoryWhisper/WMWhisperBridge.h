#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

const char * _Nullable wm_whisper_transcribe(const char * _Nonnull modelPath,
                                              const float * _Nonnull samples,
                                              int sampleCount,
                                              int threads,
                                              double * _Nullable elapsedSeconds,
                                              char * _Nullable * _Nullable errorOut);
void wm_whisper_free_string(const char * _Nullable value);

#ifdef __cplusplus
}
#endif
