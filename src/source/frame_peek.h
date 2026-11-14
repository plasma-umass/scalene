#ifndef SCALENE_FRAME_PEEK_H
#define SCALENE_FRAME_PEEK_H

#include <stdint.h>

// scalene._frame_peek exports, as the capsule SCALENE_FRAME_PEEK_CAPSULE, a
// function that records the code object (as an address) and the byte offset
// of the instruction tstate's innermost Python frame is executing. It
// returns 1 on success, 0 if there is no usable frame or the Python version
// doesn't need it. Async-signal-safe. See frame_peek.c.
#define SCALENE_FRAME_PEEK_CAPSULE "scalene._frame_peek.peek"

#ifdef __cplusplus
extern "C" {
#endif
typedef int (*scalene_peek_frame_fn)(PyThreadState* tstate,
                                     uintptr_t* code_out, int* offset_out);
#ifdef __cplusplus
}
#endif

#endif
