#import "WMWhisperBridge.h"
#include "whisper.h"
#include <chrono>
#include <cstring>
#include <string>

static char *wm_copy_string(const std::string &value) {
    char *out = (char *)malloc(value.size() + 1);
    if (!out) return nullptr;
    memcpy(out, value.c_str(), value.size() + 1);
    return out;
}

static whisper_context_params wm_context_params() {
    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    return cparams;
}

int wm_whisper_test_model(const char *modelPath,
                          double *elapsedSeconds,
                          char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!modelPath) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Modellpfad");
        return -1;
    }

    const auto started = std::chrono::steady_clock::now();
    whisper_context *ctx = whisper_init_from_file_with_params(modelPath, wm_context_params());
    const auto loaded = std::chrono::steady_clock::now();
    if (elapsedSeconds) {
        *elapsedSeconds = std::chrono::duration<double>(loaded - started).count();
    }
    if (!ctx) {
        if (errorOut) *errorOut = wm_copy_string("Whisper Base konnte nicht geladen werden");
        return -2;
    }

    whisper_free(ctx);
    return 0;
}

void *wm_whisper_create_context(const char *modelPath,
                                char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!modelPath) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Modellpfad");
        return nullptr;
    }

    whisper_context *ctx = whisper_init_from_file_with_params(modelPath, wm_context_params());
    if (!ctx) {
        if (errorOut) *errorOut = wm_copy_string("Whisper-Modell konnte nicht geladen werden");
        return nullptr;
    }
    return (void *)ctx;
}

int wm_whisper_run_full(void *context,
                        const float *samples,
                        int sampleCount,
                        int threads,
                        double *elapsedSeconds,
                        char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!context || !samples || sampleCount <= 0) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Kontext oder Audiodaten");
        return -1;
    }

    whisper_context *ctx = (whisper_context *)context;
    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.print_realtime = false;
    params.print_progress = false;
    params.print_timestamps = false;
    params.print_special = false;
    params.translate = false;
    params.language = "de";
    params.n_threads = threads > 0 ? threads : 2;
    params.offset_ms = 0;
    params.no_context = true;
    params.single_segment = false;
    params.no_timestamps = true;
    params.suppress_blank = true;

    const auto started = std::chrono::steady_clock::now();
    const int rc = whisper_full(ctx, params, samples, sampleCount);
    const auto finished = std::chrono::steady_clock::now();
    if (elapsedSeconds) {
        *elapsedSeconds = std::chrono::duration<double>(finished - started).count();
    }

    if (rc != 0) {
        if (errorOut) *errorOut = wm_copy_string("Whisper konnte das Audio nicht verarbeiten");
        return rc;
    }
    return 0;
}

const char *wm_whisper_copy_text(void *context,
                                 char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!context) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Whisper-Kontext");
        return nullptr;
    }

    whisper_context *ctx = (whisper_context *)context;
    std::string result;
    const int count = whisper_full_n_segments(ctx);
    for (int i = 0; i < count; ++i) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) result += text;
    }

    while (!result.empty() && (result.front() == ' ' || result.front() == '\n' || result.front() == '\t')) result.erase(result.begin());
    while (!result.empty() && (result.back() == ' ' || result.back() == '\n' || result.back() == '\t')) result.pop_back();
    return wm_copy_string(result);
}

void wm_whisper_free_context(void *context) {
    if (context) whisper_free((whisper_context *)context);
}

void wm_whisper_free_string(const char *value) {
    free((void *)value);
}
