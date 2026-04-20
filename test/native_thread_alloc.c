/*
 * Reproducer helper for scalene issue #857.
 *
 * Spawns a pthread from C (no Python involvement), which performs a burst
 * of malloc/free calls large enough to trigger scalene's sampling allocator.
 * The thread has NO PyThreadState, so scalene's whereInPython() takes its
 * "no current Python frame" path.
 *
 * Build (macOS):
 *   cc -O2 -fPIC -shared -o libnative_thread_alloc.dylib native_thread_alloc.c
 * Build (Linux):
 *   cc -O2 -fPIC -shared -o libnative_thread_alloc.so  native_thread_alloc.c -lpthread
 */

#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Keep results alive so an LTO / aggressive optimizer cannot elide the
 * malloc/memset/free calls. */
static volatile unsigned long long g_sink = 0;

static void* worker(void* arg) {
    size_t iters = (size_t)(long)arg;
    /* Each iteration: 8 MB alloc, touch it, free it. Enough bytes that
     * scalene's sampling allocator (~1 MB threshold) will fire many times. */
    for (size_t i = 0; i < iters; ++i) {
        size_t n = 8 * 1024 * 1024;
        volatile char* p = (volatile char*)malloc(n);
        if (p) {
            for (size_t j = 0; j < n; j += 4096) {
                p[j] = (char)(i + j);  /* touch every page */
            }
            g_sink += (unsigned long long)(unsigned char)p[0];
            free((void*)p);
        }
    }
    return NULL;
}

/* Kicks off the worker thread and joins it. Call this from Python. */
void run_native_allocs(long iters) {
    pthread_t t;
    if (pthread_create(&t, NULL, worker, (void*)iters) == 0) {
        pthread_join(t, NULL);
    }
}
