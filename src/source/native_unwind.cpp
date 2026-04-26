// Native (C/C++) stack unwinder for Scalene.
//
// Two collection paths:
//
//   1. Direct (Python-callable): unwind_native_stack(max_frames=64)
//      Walks the calling thread's native stack synchronously. Useful for
//      diagnostics from Python; not what production CPU sampling uses,
//      because by the time CPython dispatches a Python-level signal handler
//      the C extension that was running has already returned.
//
//   2. Signal-handler path (the production path):
//        install_signal_unwinder(sig)   - register a C-level sigaction
//                                          handler that chains to whatever
//                                          handler was previously installed
//                                          (typically CPython's trampoline).
//        drain_native_stack_buffer()    - called from the Python signal
//                                          handler, returns a list of stack
//                                          tuples captured since last drain.
//      The C handler runs synchronously inside OS signal delivery, so the
//      unwound stack reflects the actually-interrupted user code (e.g. a
//      numpy call still in progress). It writes raw IPs into a fixed-size
//      lock-free ring buffer; the Python handler later drains it.
//
//   resolve_ip(ip) -> (module, symbol, offset) | None
//      via dladdr(); called at report time, not in the signal handler.
//
// Backends:
//   Linux:   vendored libunwind (UNW_LOCAL_ONLY for the direct path,
//            unw_init_local2 + UNW_INIT_SIGNAL_FRAME for the signal path).
//   macOS:   _Unwind_Backtrace from <unwind.h> (signal-safe; from a real
//            sigaction handler it walks the interrupted stack).
//   Windows: stub; both paths return empty.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <atomic>
#include <cstdint>
#include <cstring>
#include <stddef.h>

#if defined(__linux__)
#  define UNW_LOCAL_ONLY
#  include <libunwind.h>
#  include <dlfcn.h>
#  include <signal.h>
#  define SCALENE_UNWIND_AVAILABLE 1
#elif defined(__APPLE__)
#  include <unwind.h>
#  include <dlfcn.h>
#  include <signal.h>
#  define SCALENE_UNWIND_AVAILABLE 1
#else
#  define SCALENE_UNWIND_AVAILABLE 0
#endif

namespace {

constexpr int kMaxStackDepth = 64;
constexpr int kRingSize = 4096;  // power of 2; must outpace one drain interval

#if SCALENE_UNWIND_AVAILABLE

// -------- Direct (in-thread, current stack) unwind --------
//
// MUST be async-signal-safe: no malloc, no Python C API.

#if defined(__APPLE__)
struct UnwindState {
  void** ips;
  int n;
  int max_frames;
};

extern "C" _Unwind_Reason_Code unwind_cb(struct _Unwind_Context* ctx,
                                         void* arg) {
  UnwindState* s = static_cast<UnwindState*>(arg);
  if (s->n >= s->max_frames) return _URC_END_OF_STACK;
  uintptr_t ip = _Unwind_GetIP(ctx);
  if (ip == 0) return _URC_END_OF_STACK;
  s->ips[s->n++] = reinterpret_cast<void*>(ip);
  return _URC_NO_REASON;
}
#endif

int unwind_into(void** ips, int max_frames) {
#if defined(__linux__)
  unw_context_t ctx;
  unw_cursor_t cursor;
  if (unw_getcontext(&ctx) != 0) return 0;
  if (unw_init_local(&cursor, &ctx) < 0) return 0;
  int n = 0;
  while (n < max_frames) {
    unw_word_t ip = 0;
    if (unw_get_reg(&cursor, UNW_REG_IP, &ip) < 0) break;
    ips[n++] = reinterpret_cast<void*>(ip);
    int step = unw_step(&cursor);
    if (step <= 0) break;
  }
  return n;
#elif defined(__APPLE__)
  UnwindState s = { ips, 0, max_frames };
  _Unwind_Backtrace(unwind_cb, &s);
  return s.n;
#endif
}

// -------- Signal-handler unwind path --------

struct StackEntry {
  // n == 0 means "empty / not yet written"; written last with release ordering
  std::atomic<int> n;
  void* ips[kMaxStackDepth];
};

// Static storage; zero-initialized by the loader. No constructors run, which
// matters because writes happen from a signal handler.
StackEntry g_ring[kRingSize];
std::atomic<uint64_t> g_write_idx{0};
uint64_t g_read_idx = 0;  // touched only from the Python-level drain
std::atomic<uint64_t> g_dropped{0};  // ring overruns
std::atomic<uint64_t> g_handler_invocations{0};  // diagnostic
std::atomic<uint64_t> g_handler_unwound{0};      // diagnostic: nonzero unwinds

struct sigaction g_prev_action[NSIG];

// Walk the interrupted stack starting from the kernel-supplied ucontext.
// On Linux libunwind takes the ucontext directly via unw_init_local2 and
// knows how to step through the signal trampoline. On macOS _Unwind_Backtrace
// from inside a sigaction handler also walks the interrupted stack
// correctly.
int unwind_signal_frame_into(void* ucontext, void** ips, int max_frames) {
  (void)ucontext;
#if defined(__linux__)
  unw_cursor_t cursor;
  unw_context_t* uc = static_cast<unw_context_t*>(ucontext);
  if (unw_init_local2(&cursor, uc, UNW_INIT_SIGNAL_FRAME) < 0) return 0;
  int n = 0;
  while (n < max_frames) {
    unw_word_t ip = 0;
    if (unw_get_reg(&cursor, UNW_REG_IP, &ip) < 0) break;
    ips[n++] = reinterpret_cast<void*>(ip);
    int step = unw_step(&cursor);
    if (step <= 0) break;
  }
  return n;
#elif defined(__APPLE__)
  UnwindState s = { ips, 0, max_frames };
  _Unwind_Backtrace(unwind_cb, &s);
  return s.n;
#endif
}

void scalene_signal_unwinder(int sig, siginfo_t* si, void* ucontext) {
  g_handler_invocations.fetch_add(1, std::memory_order_relaxed);

  // Reserve a ring slot. relaxed is fine: drain side uses an absolute index
  // that monotonically increases, and the per-entry .n release/acquire pair
  // synchronizes the IP payload.
  uint64_t idx = g_write_idx.fetch_add(1, std::memory_order_relaxed);
  StackEntry* e = &g_ring[idx % kRingSize];

  // If a previous write to this slot hasn't yet been read, count it as a
  // drop. We still overwrite — losing old samples is preferable to losing
  // new ones in the steady state.
  int prev_n = e->n.load(std::memory_order_relaxed);
  if (prev_n != 0) g_dropped.fetch_add(1, std::memory_order_relaxed);

  void* tmp[kMaxStackDepth];
  int n = unwind_signal_frame_into(ucontext, tmp, kMaxStackDepth);
  if (n > 0) {
    g_handler_unwound.fetch_add(1, std::memory_order_relaxed);
    std::memcpy(e->ips, tmp, n * sizeof(void*));
  }
  // Publish: the IPs are visible iff the reader sees n > 0.
  e->n.store(n, std::memory_order_release);

  // Chain to the previously installed handler so CPython's pending-signal
  // dispatch (which eventually invokes the Python-level cpu_signal_handler)
  // still runs. Without this, our Python handler would never fire.
  struct sigaction* prev = &g_prev_action[sig];
  if (prev->sa_flags & SA_SIGINFO) {
    if (prev->sa_sigaction) prev->sa_sigaction(sig, si, ucontext);
  } else if (prev->sa_handler != SIG_IGN && prev->sa_handler != SIG_DFL) {
    prev->sa_handler(sig);
  }
}

#endif  // SCALENE_UNWIND_AVAILABLE

PyObject* py_unwind_native_stack(PyObject* /*self*/, PyObject* args) {
  int max_frames = 64;
  if (!PyArg_ParseTuple(args, "|i", &max_frames)) return nullptr;
  if (max_frames < 0) max_frames = 0;
  if (max_frames > 512) max_frames = 512;

#if SCALENE_UNWIND_AVAILABLE
  void* ips[512];
  int n;
  Py_BEGIN_ALLOW_THREADS
  n = unwind_into(ips, max_frames + 2 > 512 ? 512 : max_frames + 2);
  Py_END_ALLOW_THREADS

  int skip = n >= 2 ? 2 : n;
  int kept = n - skip;
  if (kept > max_frames) kept = max_frames;

  PyObject* tup = PyTuple_New(kept);
  if (!tup) return nullptr;
  for (int i = 0; i < kept; i++) {
    PyObject* v = PyLong_FromVoidPtr(ips[i + skip]);
    if (!v) { Py_DECREF(tup); return nullptr; }
    PyTuple_SET_ITEM(tup, i, v);
  }
  return tup;
#else
  (void)max_frames;
  return PyTuple_New(0);
#endif
}

PyObject* py_resolve_ip(PyObject* /*self*/, PyObject* arg) {
#if SCALENE_UNWIND_AVAILABLE
  void* ip = PyLong_AsVoidPtr(arg);
  if (PyErr_Occurred()) return nullptr;
  Dl_info info;
  if (dladdr(ip, &info) == 0 || info.dli_sname == nullptr) {
    Py_RETURN_NONE;
  }
  const char* fname = info.dli_fname ? info.dli_fname : "";
  long offset = static_cast<long>(
      reinterpret_cast<const char*>(ip) -
      reinterpret_cast<const char*>(info.dli_saddr));
  return Py_BuildValue("(ssl)", fname, info.dli_sname, offset);
#else
  (void)arg;
  Py_RETURN_NONE;
#endif
}

PyObject* py_warmup(PyObject* /*self*/, PyObject* /*args*/) {
#if SCALENE_UNWIND_AVAILABLE
  void* ips[8];
  unwind_into(ips, 8);
#endif
  Py_RETURN_NONE;
}

PyObject* py_install_signal_unwinder(PyObject* /*self*/, PyObject* arg) {
#if SCALENE_UNWIND_AVAILABLE
  long sig_l = PyLong_AsLong(arg);
  if (PyErr_Occurred()) return nullptr;
  if (sig_l <= 0 || sig_l >= NSIG) {
    PyErr_SetString(PyExc_ValueError, "signal number out of range");
    return nullptr;
  }
  int sig = static_cast<int>(sig_l);

  // Always (re-)install. Scalene's enable_signals() is called more than once
  // and each call routes signal.signal() through CPython, which replaces our
  // C handler with CPython's trampoline. Re-install captures whichever
  // trampoline is current as the chained "previous" handler.
  struct sigaction sa;
  std::memset(&sa, 0, sizeof(sa));
  sa.sa_sigaction = scalene_signal_unwinder;
  sa.sa_flags = SA_SIGINFO | SA_RESTART;
  sigemptyset(&sa.sa_mask);

  // Block the signal while we swap, so our handler can't fire mid-update of
  // g_prev_action (which it reads to chain).
  sigset_t blocked;
  sigset_t prev_mask;
  sigemptyset(&blocked);
  sigaddset(&blocked, sig);
  pthread_sigmask(SIG_BLOCK, &blocked, &prev_mask);

  struct sigaction old;
  int rc = sigaction(sig, &sa, &old);

  // Avoid chaining-to-self: if a prior call already installed our handler,
  // keep the previous-previous as the chain target.
  if (rc == 0 && old.sa_sigaction != scalene_signal_unwinder) {
    g_prev_action[sig] = old;
  }

  pthread_sigmask(SIG_SETMASK, &prev_mask, nullptr);

  if (rc != 0) {
    PyErr_SetFromErrno(PyExc_OSError);
    return nullptr;
  }
  Py_RETURN_TRUE;
#else
  (void)arg;
  Py_RETURN_FALSE;
#endif
}

PyObject* py_drain_native_stack_buffer(PyObject* /*self*/, PyObject* /*args*/) {
#if SCALENE_UNWIND_AVAILABLE
  uint64_t end = g_write_idx.load(std::memory_order_acquire);
  uint64_t start = g_read_idx;
  if (end - start > static_cast<uint64_t>(kRingSize)) {
    // Reader fell behind by more than the ring; skip ahead, but count drops.
    g_dropped.fetch_add((end - start) - kRingSize, std::memory_order_relaxed);
    start = end - kRingSize;
  }

  PyObject* result = PyList_New(0);
  if (!result) return nullptr;

  for (uint64_t i = start; i < end; i++) {
    StackEntry* e = &g_ring[i % kRingSize];
    int n = e->n.load(std::memory_order_acquire);
    if (n <= 0) continue;
    PyObject* tup = PyTuple_New(n);
    if (!tup) { Py_DECREF(result); return nullptr; }
    for (int j = 0; j < n; j++) {
      PyObject* v = PyLong_FromVoidPtr(e->ips[j]);
      if (!v) { Py_DECREF(tup); Py_DECREF(result); return nullptr; }
      PyTuple_SET_ITEM(tup, j, v);
    }
    if (PyList_Append(result, tup) != 0) {
      Py_DECREF(tup); Py_DECREF(result); return nullptr;
    }
    Py_DECREF(tup);
    // Mark slot as consumed so a subsequent overwrite isn't counted as a drop.
    e->n.store(0, std::memory_order_release);
  }
  g_read_idx = end;
  return result;
#else
  return PyList_New(0);
#endif
}

PyObject* py_handler_status(PyObject* /*self*/, PyObject* arg) {
#if SCALENE_UNWIND_AVAILABLE
  long sig_l = PyLong_AsLong(arg);
  if (PyErr_Occurred()) return nullptr;
  int sig = static_cast<int>(sig_l);
  struct sigaction cur;
  std::memset(&cur, 0, sizeof(cur));
  if (sigaction(sig, nullptr, &cur) != 0) {
    PyErr_SetFromErrno(PyExc_OSError);
    return nullptr;
  }
  void* current_handler;
  if (cur.sa_flags & SA_SIGINFO) {
    current_handler = reinterpret_cast<void*>(cur.sa_sigaction);
  } else {
    current_handler = reinterpret_cast<void*>(cur.sa_handler);
  }
  void* our_handler = reinterpret_cast<void*>(&scalene_signal_unwinder);
  return Py_BuildValue("(KKi)",
                       (unsigned long long)current_handler,
                       (unsigned long long)our_handler,
                       cur.sa_flags);
#else
  (void)arg;
  Py_RETURN_NONE;
#endif
}

PyObject* py_dropped_count(PyObject* /*self*/, PyObject* /*args*/) {
#if SCALENE_UNWIND_AVAILABLE
  return PyLong_FromUnsignedLongLong(
      g_dropped.load(std::memory_order_relaxed));
#else
  return PyLong_FromLong(0);
#endif
}

PyObject* py_diag_counts(PyObject* /*self*/, PyObject* /*args*/) {
#if SCALENE_UNWIND_AVAILABLE
  return Py_BuildValue("(KKK)",
      (unsigned long long)g_handler_invocations.load(std::memory_order_relaxed),
      (unsigned long long)g_handler_unwound.load(std::memory_order_relaxed),
      (unsigned long long)g_write_idx.load(std::memory_order_relaxed));
#else
  return Py_BuildValue("(KKK)", 0ULL, 0ULL, 0ULL);
#endif
}

PyMethodDef methods[] = {
    {"unwind_native_stack", py_unwind_native_stack, METH_VARARGS,
     "Walk the calling thread's native stack now; return a tuple of IPs."},
    {"resolve_ip", py_resolve_ip, METH_O,
     "Resolve an IP to (module, symbol, offset) via dladdr; None if unresolved."},
    {"warmup", py_warmup, METH_NOARGS,
     "Pre-fault the unwinder so first call from a signal handler is safe."},
    {"install_signal_unwinder", py_install_signal_unwinder, METH_O,
     "Install a sigaction handler on the given signal that captures the "
     "interrupted stack into the ring buffer and chains to the previous "
     "handler. Idempotent. Returns True on first install, False thereafter."},
    {"drain_native_stack_buffer", py_drain_native_stack_buffer, METH_NOARGS,
     "Return a list of stack tuples captured by the signal handler since the "
     "last drain. Each tuple is innermost-first IPs."},
    {"dropped_count", py_dropped_count, METH_NOARGS,
     "Total samples lost to ring-buffer overrun (drain-side fell behind)."},
    {"handler_status", py_handler_status, METH_O,
     "Diagnostic: returns (current_handler_addr, our_handler_addr, flags) "
     "for the given signal. If addrs don't match, our handler was replaced."},
    {"diag_counts", py_diag_counts, METH_NOARGS,
     "Diagnostic: (handler_invocations, successful_unwinds, write_idx)."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "_scalene_unwind", nullptr, -1, methods,
    nullptr, nullptr, nullptr, nullptr,
};

}  // namespace

extern "C" PyObject* PyInit__scalene_unwind(void) {
  PyObject* m = PyModule_Create(&moduledef);
  if (!m) return nullptr;
  PyModule_AddIntConstant(m, "available", SCALENE_UNWIND_AVAILABLE);
  return m;
}
