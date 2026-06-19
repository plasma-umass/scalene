// -*- C++ -*-
#ifndef SCALENE_EINTR_RETRY_HPP
#define SCALENE_EINTR_RETRY_HPP

// ---------------------------------------------------------------------------
// EINTR-retry interposers for blocking "wait" syscalls.
//
// Why this exists
// ---------------
// Scalene profiles wall-clock time by default (--use-virtual-time is False),
// which arms ITIMER_REAL and delivers SIGALRM periodically -- including while
// the process is blocked inside a native syscall. Scalene already installs its
// handlers with SA_RESTART (via siginterrupt(sig, False)), so *restartable*
// syscalls (read/write/connect/recv/...) are resumed transparently by the
// kernel. But per signal(7), poll(2)/select(2)/ppoll(2)/pselect(2)/
// epoll_wait(2) are *never* restarted regardless of SA_RESTART: they always
// fail with EINTR when a handler runs.
//
// Well-behaved code retries on EINTR (CPython does this for its own I/O since
// PEP 475), but native libraries that don't will spuriously fail. The concrete
// report (issue #1060) is the Microsoft ODBC Driver 18 for SQL Server: its TCP
// provider performs a non-blocking connect() followed by poll()/select() with a
// login timeout. A SIGALRM landing on that poll returns EINTR, which the driver
// surfaces as WSAEINTR (0x2714 / 10004) and a failed connection -- only on
// Linux, because on Windows Scalene samples via threads, not signals.
//
// Because libscalene is LD_PRELOADed whenever memory profiling is enabled
// (the default), we can interpose the non-restartable wait calls here and
// retry them on EINTR, recomputing the remaining timeout so the call's
// deadline is preserved.
//
// Only Scalene-induced EINTR is absorbed
// --------------------------------------
// We must NOT swallow EINTR caused by signals the application cares about
// (e.g. SIGINT/Ctrl-C, SIGTERM), or we would delay their delivery while a
// thread sits in poll(). To distinguish, we wrap the handler of whichever
// timer signal Scalene arms (learned by interposing setitimer) with a thin
// shim that bumps a generation counter before chaining to the original
// handler. The retry loop only continues when that counter advanced across the
// interrupted call; an EINTR with an unchanged counter (some other signal)
// is returned to the caller unchanged.
//
// Set SCALENE_DISABLE_EINTR_RETRY=1 to turn this off (pure pass-through).
// ---------------------------------------------------------------------------

#if !defined(_WIN32)

#include <dlfcn.h>
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/select.h>
#include <sys/time.h>
#include <time.h>

#if defined(__linux__)
#include <sys/epoll.h>
#endif

namespace scalene {
namespace eintr {

// Reaching the real libc implementation differs by platform:
//
//  * Linux (LD_PRELOAD): our definition shadows the public symbol, so a direct
//    call would recurse. We resolve the next definition with
//    dlsym(RTLD_NEXT, ...) and cache it.
//
//  * macOS (__interpose): the interpose table only redirects calls made from
//    *other* images; a direct call to the libc symbol from within this library
//    binds to the real implementation. (dlsym(RTLD_NEXT, ...) here incorrectly
//    returns our own interposer, causing infinite recursion -- this mirrors the
//    pattern used by Heap-Layers' memcpy wrapper, which calls ::memcpy
//    directly.)
#if defined(__APPLE__)

#define SCALENE_REAL_DECL(rettype, fn, params) /* nothing */
#define SCALENE_REAL_OK(fn) (true)
#define SCALENE_REAL_CALL(fn, ...) (::fn(__VA_ARGS__))

#else

#define SCALENE_REAL_DECL(rettype, fn, params)                              \
  static rettype(*scalene_real_##fn) params =                               \
      reinterpret_cast<rettype(*) params>(dlsym(RTLD_NEXT, #fn))
#define SCALENE_REAL_OK(fn) (scalene_real_##fn != nullptr)
#define SCALENE_REAL_CALL(fn, ...) (scalene_real_##fn(__VA_ARGS__))

#endif

// Bumped by our wrapper each time one of Scalene's profiling timer signals is
// delivered. `volatile sig_atomic_t` is async-signal-safe to write from a
// handler and read from the interposers; the exact value never matters, only
// whether it changed across an interrupted call.
static volatile sig_atomic_t g_timer_generation = 0;

// Original handlers for the signals we have wrapped, indexed by signal number.
static struct sigaction g_orig[NSIG];
static pthread_mutex_t g_arm_mutex = PTHREAD_MUTEX_INITIALIZER;

// One-time check of the opt-out environment variable.
static inline bool disabled() {
  static const bool d = []() {
    const char* e = getenv("SCALENE_DISABLE_EINTR_RETRY");
    return e != nullptr && e[0] != '\0' && e[0] != '0';
  }();
  return d;
}

// Thin shim that runs in place of Scalene's timer-signal handler: record that
// a Scalene signal fired, then chain to the real handler so sampling is
// unaffected.
static void generation_shim(int sig, siginfo_t* info, void* ctx) {
  g_timer_generation++;
  if (sig < 0 || sig >= NSIG) {
    return;
  }
  const struct sigaction& o = g_orig[sig];
  if (o.sa_flags & SA_SIGINFO) {
    if (o.sa_sigaction) {
      o.sa_sigaction(sig, info, ctx);
    }
  } else {
    void (*h)(int) = o.sa_handler;
    if (h != SIG_IGN && h != SIG_DFL && h != nullptr) {
      h(sig);
    }
  }
}

// Ensure our generation shim is installed in front of whatever handler is
// currently registered for `sig`. Idempotent and safe to call repeatedly
// (e.g. after Scalene re-installs handlers on fork or restart).
static void arm_for_signal(int sig) {
  if (sig <= 0 || sig >= NSIG) {
    return;
  }
  pthread_mutex_lock(&g_arm_mutex);
  struct sigaction cur;
  if (sigaction(sig, nullptr, &cur) == 0) {
    const bool is_ours =
        (cur.sa_flags & SA_SIGINFO) && cur.sa_sigaction == generation_shim;
    const bool has_handler =
        (cur.sa_flags & SA_SIGINFO)
            ? (cur.sa_sigaction != nullptr)
            : (cur.sa_handler != SIG_DFL && cur.sa_handler != SIG_IGN);
    if (!is_ours && has_handler) {
      g_orig[sig] = cur;
      struct sigaction na = cur;
      // Chain via sa_sigaction so we always forward siginfo/context.
      na.sa_flags = (cur.sa_flags & ~SA_RESETHAND) | SA_SIGINFO;
      na.sa_sigaction = generation_shim;
      sigaction(sig, &na, nullptr);
    }
  }
  pthread_mutex_unlock(&g_arm_mutex);
}

static inline int which_to_signo(int which) {
  switch (which) {
    case ITIMER_REAL:
      return SIGALRM;
    case ITIMER_VIRTUAL:
      return SIGVTALRM;
    case ITIMER_PROF:
      return SIGPROF;
    default:
      return -1;
  }
}

static inline long ts_diff_us(const struct timespec& a,
                              const struct timespec& b) {
  return (a.tv_sec - b.tv_sec) * 1000000L + (a.tv_nsec - b.tv_nsec) / 1000L;
}

// --- interposed setitimer: arms the guard, then delegates -------------------

static int setitimer_impl(int which, const struct itimerval* nv,
                          struct itimerval* ov) {
  SCALENE_REAL_DECL(int, setitimer,
                    (int, const struct itimerval*, struct itimerval*));
  // Arm our guard for the signal this timer delivers, but only when actually
  // starting a timer (a zero it_value disarms it).
  if (!disabled() && nv &&
      (nv->it_value.tv_sec != 0 || nv->it_value.tv_usec != 0)) {
    const int sig = which_to_signo(which);
    if (sig > 0) {
      arm_for_signal(sig);
    }
  }
  if (!SCALENE_REAL_OK(setitimer)) {
    errno = ENOSYS;
    return -1;
  }
  return SCALENE_REAL_CALL(setitimer, which, nv, ov);
}

// --- interposed poll --------------------------------------------------------

static int poll_impl(struct pollfd* fds, nfds_t nfds, int timeout) {
  SCALENE_REAL_DECL(int, poll, (struct pollfd*, nfds_t, int));
  if (!SCALENE_REAL_OK(poll)) {
    errno = ENOSYS;
    return -1;
  }
  // Non-blocking poll: nothing to retry against.
  if (disabled() || timeout == 0) {
    return SCALENE_REAL_CALL(poll, fds, nfds, timeout);
  }
  const bool timed = timeout > 0;
  struct timespec start;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
  }
  int remaining = timeout;
  for (;;) {
    const sig_atomic_t gen = g_timer_generation;
    const int r = SCALENE_REAL_CALL(poll, fds, nfds, timed ? remaining : -1);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;  // EINTR from some other signal: let the caller see it.
    }
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      const long elapsed_us = ts_diff_us(now, start);
      const long rem_us = (long)timeout * 1000L - elapsed_us;
      remaining = rem_us <= 0 ? 0 : (int)(rem_us / 1000L);
    }
  }
}

// --- interposed select ------------------------------------------------------

static int select_impl(int nfds, fd_set* rd, fd_set* wr, fd_set* ex,
                       struct timeval* tv) {
  SCALENE_REAL_DECL(int, select,
                    (int, fd_set*, fd_set*, fd_set*, struct timeval*));
  if (!SCALENE_REAL_OK(select)) {
    errno = ENOSYS;
    return -1;
  }
  if (disabled()) {
    return SCALENE_REAL_CALL(select, nfds, rd, wr, ex, tv);
  }
  // Save the input sets; select() leaves them unspecified on EINTR.
  fd_set srd, swr, sex;
  if (rd) srd = *rd;
  if (wr) swr = *wr;
  if (ex) sex = *ex;
  const bool timed = (tv != nullptr);
  struct timespec start;
  long total_us = 0;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
    total_us = (long)tv->tv_sec * 1000000L + tv->tv_usec;
  }
  struct timeval local;
  for (;;) {
    if (rd) *rd = srd;
    if (wr) *wr = swr;
    if (ex) *ex = sex;
    struct timeval* tvp = nullptr;
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      long rem_us = total_us - ts_diff_us(now, start);
      if (rem_us < 0) rem_us = 0;
      local.tv_sec = rem_us / 1000000L;
      local.tv_usec = rem_us % 1000000L;
      tvp = &local;
    }
    const sig_atomic_t gen = g_timer_generation;
    const int r = SCALENE_REAL_CALL(select, nfds, rd, wr, ex, tvp);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;
    }
  }
}

// --- interposed pselect (POSIX) ---------------------------------------------

static int pselect_impl(int nfds, fd_set* rd, fd_set* wr, fd_set* ex,
                        const struct timespec* timeout, const sigset_t* mask) {
  SCALENE_REAL_DECL(int, pselect,
                    (int, fd_set*, fd_set*, fd_set*, const struct timespec*,
                     const sigset_t*));
  if (!SCALENE_REAL_OK(pselect)) {
    errno = ENOSYS;
    return -1;
  }
  if (disabled()) {
    return SCALENE_REAL_CALL(pselect, nfds, rd, wr, ex, timeout, mask);
  }
  fd_set srd, swr, sex;
  if (rd) srd = *rd;
  if (wr) swr = *wr;
  if (ex) sex = *ex;
  const bool timed = (timeout != nullptr);
  struct timespec start;
  long total_us = 0;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
    total_us = (long)timeout->tv_sec * 1000000L + timeout->tv_nsec / 1000L;
  }
  struct timespec local;
  for (;;) {
    if (rd) *rd = srd;
    if (wr) *wr = swr;
    if (ex) *ex = sex;
    const struct timespec* tsp = nullptr;
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      long rem_us = total_us - ts_diff_us(now, start);
      if (rem_us < 0) rem_us = 0;
      local.tv_sec = rem_us / 1000000L;
      local.tv_nsec = (rem_us % 1000000L) * 1000L;
      tsp = &local;
    }
    const sig_atomic_t gen = g_timer_generation;
    const int r = SCALENE_REAL_CALL(pselect, nfds, rd, wr, ex, tsp, mask);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;
    }
  }
}

#if defined(__linux__)

// --- interposed ppoll (Linux) ----------------------------------------------

static int ppoll_impl(struct pollfd* fds, nfds_t nfds,
                      const struct timespec* timeout, const sigset_t* mask) {
  SCALENE_REAL_DECL(int, ppoll,
                    (struct pollfd*, nfds_t, const struct timespec*,
                     const sigset_t*));
  if (!SCALENE_REAL_OK(ppoll)) {
    errno = ENOSYS;
    return -1;
  }
  if (disabled() || (timeout && timeout->tv_sec == 0 && timeout->tv_nsec == 0)) {
    return SCALENE_REAL_CALL(ppoll, fds, nfds, timeout, mask);
  }
  const bool timed = (timeout != nullptr);
  struct timespec start;
  long total_us = 0;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
    total_us = (long)timeout->tv_sec * 1000000L + timeout->tv_nsec / 1000L;
  }
  struct timespec local;
  for (;;) {
    const struct timespec* tsp = nullptr;
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      long rem_us = total_us - ts_diff_us(now, start);
      if (rem_us < 0) rem_us = 0;
      local.tv_sec = rem_us / 1000000L;
      local.tv_nsec = (rem_us % 1000000L) * 1000L;
      tsp = &local;
    }
    const sig_atomic_t gen = g_timer_generation;
    const int r = SCALENE_REAL_CALL(ppoll, fds, nfds, tsp, mask);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;
    }
  }
}

// --- interposed epoll_wait / epoll_pwait (Linux) ----------------------------

static int epoll_wait_impl(int epfd, struct epoll_event* events, int maxevents,
                           int timeout) {
  SCALENE_REAL_DECL(int, epoll_wait, (int, struct epoll_event*, int, int));
  if (!SCALENE_REAL_OK(epoll_wait)) {
    errno = ENOSYS;
    return -1;
  }
  if (disabled() || timeout == 0) {
    return SCALENE_REAL_CALL(epoll_wait, epfd, events, maxevents, timeout);
  }
  const bool timed = timeout > 0;
  struct timespec start;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
  }
  int remaining = timeout;
  for (;;) {
    const sig_atomic_t gen = g_timer_generation;
    const int r =
        SCALENE_REAL_CALL(epoll_wait, epfd, events, maxevents,
                          timed ? remaining : -1);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;
    }
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      const long elapsed_us = ts_diff_us(now, start);
      const long rem_us = (long)timeout * 1000L - elapsed_us;
      remaining = rem_us <= 0 ? 0 : (int)(rem_us / 1000L);
    }
  }
}

static int epoll_pwait_impl(int epfd, struct epoll_event* events, int maxevents,
                            int timeout, const sigset_t* mask) {
  SCALENE_REAL_DECL(int, epoll_pwait,
                    (int, struct epoll_event*, int, int, const sigset_t*));
  if (!SCALENE_REAL_OK(epoll_pwait)) {
    errno = ENOSYS;
    return -1;
  }
  if (disabled() || timeout == 0) {
    return SCALENE_REAL_CALL(epoll_pwait, epfd, events, maxevents, timeout,
                             mask);
  }
  const bool timed = timeout > 0;
  struct timespec start;
  if (timed) {
    clock_gettime(CLOCK_MONOTONIC, &start);
  }
  int remaining = timeout;
  for (;;) {
    const sig_atomic_t gen = g_timer_generation;
    const int r = SCALENE_REAL_CALL(epoll_pwait, epfd, events, maxevents,
                                    timed ? remaining : -1, mask);
    if (r >= 0 || errno != EINTR) {
      return r;
    }
    if (g_timer_generation == gen) {
      return r;
    }
    if (timed) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      const long elapsed_us = ts_diff_us(now, start);
      const long rem_us = (long)timeout * 1000L - elapsed_us;
      remaining = rem_us <= 0 ? 0 : (int)(rem_us / 1000L);
    }
  }
}

#endif  // __linux__

}  // namespace eintr
}  // namespace scalene

#endif  // !_WIN32
#endif  // SCALENE_EINTR_RETRY_HPP
