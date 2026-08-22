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

static void wm_persist_stage(NSString *value) {
    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    [defaults setObject:value forKey:@"WMWhisperLastStage"];
    [defaults synchronize];
}

static whisper_context_params wm_context_params() {
    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    return cparams;
}

static bool wm_encoder_begin_callback(struct whisper_context *, struct whisper_state *, void *) {
    wm_persist_stage(@"6K: whisper_full Encoder startet");
    return true;
}

static void wm_progress_callback(struct whisper_context *, struct whisper_state *, int progress, void *) {
    if (progress == 0) {
        wm_persist_stage(@"6J: whisper_full Hauptloop gestartet");
    }
}

static void wm_new_segment_callback(struct whisper_context *, struct whisper_state *, int, void *) {
    wm_persist_stage(@"6L: Decoder Segment erzeugt");
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

int wm_whisper_pcm_to_mel(void *context,
                          const float *samples,
                          int sampleCount,
                          int threads,
                          char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!context || !samples || sampleCount <= 0) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Kontext oder Audiodaten");
        return -1;
    }
    whisper_context *ctx = (whisper_context *)context;
    const int rc = whisper_pcm_to_mel(ctx, samples, sampleCount, threads > 0 ? threads : 1);
    if (rc != 0 && errorOut) *errorOut = wm_copy_string("PCM → Mel fehlgeschlagen");
    return rc;
}

int wm_whisper_encode_only(void *context,
                           int offset,
                           int threads,
                           char **errorOut) {
    if (errorOut) *errorOut = nullptr;
    if (!context) {
        if (errorOut) *errorOut = wm_copy_string("Ungültiger Whisper-Kontext");
        return -1;
    }
    whisper_context *ctx = (whisper_context *)context;
    const int rc = whisper_encode(ctx, offset, threads > 0 ? threads : 1);
    if (rc != 0 && errorOut) *errorOut = wm_copy_string("Whisper Encoder fehlgeschlagen");
    return rc;
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
    params.n_threads = threads > 0 ? threads : 1;
    params.offset_ms = 0;
    params.no_context = true;
    params.single_segment = true;
    params.no_timestamps = true;
    params.suppress_blank = true;

    // A10-safe baseline: no fallback fan-out and only one greedy decoder.
    // This does not change the model weights or language; it only reduces runtime work/memory.
    params.greedy.best_of = 1;
    params.temperature_inc = 0.0f;

    params.progress_callback = wm_progress_callback;
    params.encoder_begin_callback = wm_encoder_begin_callback;
    params.new_segment_callback = wm_new_segment_callback;

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
