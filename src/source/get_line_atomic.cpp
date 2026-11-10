#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <heaplayers.h>
#include <string.h>

#include <mutex>

// This uses Python's buffer interface to view a mmap buffer passed in,
// which we assume has a layout of [ uint64_t | HL::SpinLock ].
//
// We assume that the lock region has been fully initialized at this point,
// since initialization occurs at the bootstrapping of the per-thread heap
//
// This is derived in part from
// https://docs.python.org/3/extending/extending.html
//
// FIXME: Encapsulate under scalene namespace
// TODO: Wrap in Python library with ContextManager

namespace {
// Releases a Py_buffer obtained via PyArg_ParseTuple("s*") on scope exit.
// Without this, every call leaked a buffer export on each argument (which,
// among other things, keeps the mmap objects from ever being closed).
struct BufferGuard {
  Py_buffer view;
  bool held = false;
  ~BufferGuard() {
    if (held) PyBuffer_Release(&view);
  }
};
}  // namespace

// Layout of the shared lock page (see SampleFile in samplefile.hpp):
//
//   [0, 8)                     uint64_t write position (end of valid data)
//   [8, 8 + sizeof(SpinLock))  HL::SpinLock guarding the log
//   [kGenerationOffset, +8)    uint64_t generation, bumped on every reset
//
// The page is created zero-filled by ftruncate, so the generation starts at
// 0. Only this reader touches the generation; the native writer never does.
//
// Reader state (the ``lastpos`` argument) is [uint64 pos, uint64 generation].
// An 8-byte buffer is still accepted (position only, no reset support).
static constexpr size_t kGenerationOffset = 64;

static PyObject* get_line_atomic(PyObject* self, PyObject* args) {
  BufferGuard lock_mmap, signal_mmap, result_bytearray, lastpos_buf;
  int may_reset = 0;
  if (!PyArg_ParseTuple(
          args, "s*s*s*s*|p", &lock_mmap.view, &signal_mmap.view,
          &result_bytearray.view, &lastpos_buf.view,
          &may_reset))  // "s*" means readable/writeable buffer as per
                        // https://docs.python.org/3/c-api/arg.html
                        // Buffer protocol is found here
                        // https://docs.python.org/3/c-api/buffer.html
    return NULL;
  lock_mmap.held = signal_mmap.held = result_bytearray.held =
      lastpos_buf.held = true;

  using LockType = HL::SpinLock;
  static_assert(sizeof(uint64_t) + sizeof(LockType) <= kGenerationOffset,
                "generation counter would overlap the spin lock");
  if (lock_mmap.view.len <
          static_cast<Py_ssize_t>(kGenerationOffset + sizeof(uint64_t)) ||
      lastpos_buf.view.len < static_cast<Py_ssize_t>(sizeof(uint64_t))) {
    PyErr_SetString(PyExc_ValueError,
                    "get_line_atomic: lock or lastpos buffer too small");
    return NULL;
  }
  if (result_bytearray.view.readonly || lastpos_buf.view.readonly ||
      lock_mmap.view.readonly) {
    PyErr_SetString(PyExc_ValueError,
                    "get_line_atomic: lock, result and lastpos buffers must "
                    "be writable");
    return NULL;
  }
  const bool has_generation =
      lastpos_buf.view.len >= static_cast<Py_ssize_t>(2 * sizeof(uint64_t));

  auto lock_page = reinterpret_cast<char*>(lock_mmap.view.buf);
  auto writer_pos = reinterpret_cast<uint64_t*>(lock_page);
  auto lock = reinterpret_cast<LockType*>(lock_page + sizeof(uint64_t));
  auto generation =
      reinterpret_cast<uint64_t*>(lock_page + kGenerationOffset);

  std::lock_guard<LockType> theLock(*lock);

  auto lastpos = reinterpret_cast<uint64_t*>(lastpos_buf.view.buf);
  auto reader_generation = has_generation ? lastpos + 1 : nullptr;

  if (reader_generation && *reader_generation != *generation) {
    // The log was reset (by the owning process) since this reader last
    // looked; its position refers to old data. Start over at the beginning
    // of the current generation.
    *lastpos = 0;
    *reader_generation = *generation;
  }

  // Valid data ends at the writer's position (clamped to the buffer, in case
  // it is corrupt). Bounding reads by it, not just by the buffer, matters
  // once the log is reused: bytes past it are stale records from before the
  // last reset.
  const auto signal_len = static_cast<uint64_t>(signal_mmap.view.len);
  const uint64_t data_end = *writer_pos < signal_len ? *writer_pos : signal_len;

  if (*lastpos >= data_end) {
    // Fully drained. The log is append-only, so without a reset the writer
    // eventually runs out of room and has to drop samples (issue #1122).
    // Now that every record has been consumed, the owner rewinds the log.
    // Both positions change under the lock the writer also takes, so the
    // writer simply continues at offset 0.
    if (may_reset && reader_generation && *writer_pos != 0 &&
        *lastpos == *writer_pos) {
      *writer_pos = 0;
      *lastpos = 0;
      *generation += 1;
      *reader_generation = *generation;
    }
    Py_RETURN_FALSE;
  }

  auto current_iter = reinterpret_cast<char*>(signal_mmap.view.buf) + *lastpos;
  auto start = current_iter;
  auto result_iter = reinterpret_cast<char*>(result_bytearray.view.buf);

  // Bound the newline search by BOTH the valid bytes remaining in the signal
  // buffer and the capacity of the result buffer. The search used to be
  // bounded only by the result buffer's size, so with lastpos near the end of
  // the mapping memchr read past it (SIGBUS/SIGSEGV, or garbage from adjacent
  // memory; issue #1117). Limiting it to the result capacity also guarantees
  // that the line plus its newline (len + 1 bytes) fits in the result buffer.
  const uint64_t remaining = data_end - *lastpos;
  const auto capacity = static_cast<uint64_t>(result_bytearray.view.len);
  const size_t search_len =
      static_cast<size_t>(remaining < capacity ? remaining : capacity);

  char* nl = reinterpret_cast<char*>(memchr(current_iter, '\n', search_len));
  size_t len = (nl == nullptr) ? 0 : static_cast<size_t>(nl - start);

  if (len == 0) {
    Py_RETURN_FALSE;
  }

  // avoid 'memcpy', as Scalene interposes on it to measure memory copying
  for (size_t i = 0; i <= len; i++) {
    *(result_iter++) = *(current_iter++);
  }

  *lastpos += len + 1;

  Py_RETURN_TRUE;
}

static PyMethodDef MmapHlSpinlockMethods[] = {
    {"get_line_atomic", get_line_atomic, METH_VARARGS,
     "locks a mutex located in buffer"},
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef mmaphlspinlockmodule = {
    PyModuleDef_HEAD_INIT, "get_line_atomic", NULL, -1, MmapHlSpinlockMethods};

PyMODINIT_FUNC PyInit_get_line_atomic(void) {
  PyObject* m = PyModule_Create(&mmaphlspinlockmodule);
#ifdef Py_GIL_DISABLED
  if (m != NULL) {
    PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED);
  }
#endif
  return m;
}
