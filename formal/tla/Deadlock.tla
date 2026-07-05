------------------------------- MODULE Deadlock -------------------------------
(***************************************************************************)
(* Model of Scalene's lock/queue topology, checked for deadlock-freedom    *)
(* and for the signal-safety property that a signal handler never blocks   *)
(* on a lock.                                                              *)
(*                                                                         *)
(* Faithful to:                                                           *)
(*   - scalene/scalene_sigqueue.py:14  self.lock = threading.RLock()       *)
(*       held by the background thread ONLY while processing one item      *)
(*       run(): `with self.lock: self.process(item)`  line 47-49.          *)
(*   - scalene/scalene_sigqueue.py:11  queue.SimpleQueue  -- the signal    *)
(*       handler enqueues with put() (lock-free); it never takes the RLock.*)
(*   - scalene/scalene_profiler.py:684,775,794  malloc/free/memcpy signal  *)
(*       handlers: do only `sigq.put(...)` (lock-free) -> NEVER block.      *)
(*   - scalene/scalene_profiler.py:1170-1178  the output path, on the MAIN *)
(*       thread, acquires ALL sigqueue locks together, in a fixed list     *)
(*       order, then flushes, then releases.                               *)
(*   - scalene/scalene_sigqueue.py:34-38 stop(): join()s the thread before *)
(*       fork; the lock is not held across the join.                       *)
(*                                                                         *)
(* Agents:                                                                 *)
(*   Workers 1..N : the per-sigqueue background daemon threads. Each holds *)
(*                  ONLY its own lock i.                                    *)
(*   Output       : the main thread; acquires locks 1..N in increasing     *)
(*                  order (a fixed global order) then releases all.        *)
(*   Handler      : a signal handler; only ever does a lock-free put.      *)
(*                                                                         *)
(* Deadlock requires a circular wait. The model lets workers and the       *)
(* output thread contend for the locks with arbitrary interleaving; TLC    *)
(* checks no reachable state is a deadlock and the handler is always       *)
(* enabled (never blocked).                                                *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    N,           \* number of sigqueues (Scalene has 3: alloc, memcpy, async)
    MaxHandler   \* bound on handler firings (keeps the state space finite)

ASSUME N \in Nat \ {0}
ASSUME MaxHandler \in Nat

Locks == 1..N

VARIABLES
    owner,      \* owner[i] \in {"free","worker","out"} : who holds lock i
                \*   ("worker" => the same-indexed background thread w=i, since a
                \*    worker only ever takes its own lock)
    wstate,     \* wstate[w] \in {"idle","holding"} : worker w's state
    ostate,     \* output thread state: "idle","acquiring","critical","releasing"
    onext,      \* next lock index the output thread will try to acquire (1..N+1)
    handlerRuns \* counter: number of times the (always-enabled) handler ran

vars == << owner, wstate, ostate, onext, handlerRuns >>

Init ==
    /\ owner = [i \in Locks |-> "free"]
    /\ wstate = [w \in Locks |-> "idle"]
    /\ ostate = "idle"
    /\ onext = 1
    /\ handlerRuns = 0

(*-----------------------------------------------------------------------*)
(* Worker w grabs its OWN lock w (only if free) to process an item.       *)
(* A worker never reaches for any other lock -> it can hold at most one.  *)
(*-----------------------------------------------------------------------*)
WorkerAcquire(w) ==
    /\ wstate[w] = "idle"
    /\ owner[w] = "free"
    /\ owner' = [owner EXCEPT ![w] = "worker"]
    /\ wstate' = [wstate EXCEPT ![w] = "holding"]
    /\ UNCHANGED << ostate, onext, handlerRuns >>

WorkerRelease(w) ==
    /\ wstate[w] = "holding"
    /\ owner' = [owner EXCEPT ![w] = "free"]
    /\ wstate' = [wstate EXCEPT ![w] = "idle"]
    /\ UNCHANGED << ostate, onext, handlerRuns >>

(*-----------------------------------------------------------------------*)
(* Output thread acquires locks 1..N in increasing order. It blocks on    *)
(* lock `onext` until that lock is free, then takes it and advances.      *)
(* Fixed global acquisition order => no circular wait with the workers,   *)
(* each of which holds only its single same-indexed lock.                 *)
(*-----------------------------------------------------------------------*)
OutputStart ==
    /\ ostate = "idle"
    /\ ostate' = "acquiring"
    /\ onext' = 1
    /\ UNCHANGED << owner, wstate, handlerRuns >>

OutputAcquire ==
    /\ ostate = "acquiring"
    /\ onext <= N
    /\ owner[onext] = "free"            \* blocks (no step) until this lock is free
    /\ owner' = [owner EXCEPT ![onext] = "out"]
    /\ onext' = onext + 1
    /\ UNCHANGED << wstate, ostate, handlerRuns >>

OutputEnterCritical ==
    /\ ostate = "acquiring"
    /\ onext = N + 1
    /\ ostate' = "critical"
    /\ UNCHANGED << owner, wstate, onext, handlerRuns >>

OutputRelease ==
    /\ ostate = "critical"
    /\ owner' = [i \in Locks |-> IF owner[i] = "out" THEN "free" ELSE owner[i]]
    /\ ostate' = "idle"
    /\ onext' = 1
    /\ UNCHANGED << wstate, handlerRuns >>

(*-----------------------------------------------------------------------*)
(* Signal handler: lock-free enqueue. ALWAYS enabled, never blocks.       *)
(* This is the crux of signal-safety: a handler interrupting any thread   *)
(* (even one holding a lock) makes progress without acquiring a lock.     *)
(*-----------------------------------------------------------------------*)
HandlerFire ==
    /\ handlerRuns < MaxHandler        \* bound only to keep the model finite
    /\ handlerRuns' = handlerRuns + 1
    /\ UNCHANGED << owner, wstate, ostate, onext >>

Next ==
    \/ \E w \in Locks: WorkerAcquire(w)
    \/ \E w \in Locks: WorkerRelease(w)
    \/ OutputStart
    \/ OutputAcquire
    \/ OutputEnterCritical
    \/ OutputRelease
    \/ HandlerFire

(* Fairness: workers eventually release their lock (WF), and the output    *)
(* thread is scheduled whenever it can progress (SF, so an intermittently   *)
(* free lock is eventually taken rather than starved by re-acquiring        *)
(* workers -- modeling a fair OS scheduler).                                *)
Fairness ==
    /\ \A w \in Locks : WF_vars(WorkerRelease(w))
    /\ SF_vars(OutputAcquire)
    /\ SF_vars(OutputEnterCritical)
    /\ WF_vars(OutputStart)

Spec == Init /\ [][Next]_vars /\ Fairness

(*-----------------------------------------------------------------------*)
(* PROPERTIES                                                            *)
(*-----------------------------------------------------------------------*)

TypeOK ==
    /\ owner \in [Locks -> {"free","worker","out"}]
    /\ wstate \in [Locks -> {"idle","holding"}]
    /\ ostate \in {"idle","acquiring","critical","releasing"}
    /\ onext \in 1..(N+1)

(* Mutual exclusion: worker w holds lock w iff owner[w]="worker"; and a    *)
(* worker and the output thread are never recorded as co-owning a lock     *)
(* (owner is a single-valued function, so this is the real content:        *)
(* a holding worker's lock is owned by "worker", not "out").               *)
MutualExclusion ==
    \A i \in Locks :
        (wstate[i] = "holding" => owner[i] = "worker")

(* Signal-safety: the handler's ability to run never depends on lock      *)
(* state -- it is enabled whenever the (artificial, finiteness-only)       *)
(* bound is not yet hit, regardless of who holds which lock. So a handler  *)
(* interrupting a lock holder still makes progress (lock-free put).        *)
(* Contrast: if the handler took a lock, ENABLED would depend on `owner`.  *)
HandlerNeverBlocks == (handlerRuns < MaxHandler) => ENABLED HandlerFire

(* Deadlock-freedom is checked by TLC's built-in deadlock detection       *)
(* (a state with no successor under Next, modulo stuttering). With        *)
(* fixed-order acquisition and single-lock workers there is no circular   *)
(* wait, so the system can always make progress.                          *)

(* Liveness: the output thread, once it starts acquiring, eventually      *)
(* reaches its critical section (no starvation under weak fairness).      *)
OutputMakesProgress == (ostate = "acquiring") ~> (ostate = "critical")
==============================================================================
