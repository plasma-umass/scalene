#ifndef SCALENE_FRAME_PEEK_H
#define SCALENE_FRAME_PEEK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Records the code object (as an address) and the byte offset of the
// instruction tstate's innermost Python frame is executing. Returns 1 on
// success, 0 if there is no usable frame or the Python version doesn't need
// it. Async-signal-safe. See frame_peek.c.
int scalene_peek_frame(PyThreadState* tstate, uintptr_t* code_out,
                       int* offset_out);

#ifdef __cplusplus
}
#endif

#endif
