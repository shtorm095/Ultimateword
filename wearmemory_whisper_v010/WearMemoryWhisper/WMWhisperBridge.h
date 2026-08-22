#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif

int wm_whisper_test_model(const char * _Nonnull modelPath,
                          double * _Nullable elapsedSeconds,
                          char * _Nullable * _Nullable errorOut);

void * _Nullable wm_whisper_create_context(const char * _Nonnull modelPath,
                                            char * _Nullable * _Nullable errorOut);

const char * _Nullable wm_whisper_transcribe_context(void * _Nonnull context,
                                                      const float * _Nonnull samples,
                                                      int sampleCount,
                                                      int threads,
                                                      double * _Nullable elapsedSeconds,
                                                      char * _Nullable * _Nullable errorOut);

void wm_whisper_free_context(void * _Nullable context);
void wm_whisper_free_string(const char * _Nullable value);

#ifdef __cplusplus
}
#endif
