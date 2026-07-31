---------------------------- MODULE SignalSafety ----------------------------
(***************************************************************************)
(* Model of Scalene's CPU-sampling signal handler racing with the         *)
(* profile-output iterator over a shared stats dictionary.                 *)
(*                                                                         *)
(* Faithful to:                                                            *)
(*   - scalene/scalene_cpu_profiler.py:154-195  (add_combined_stack writes *)
(*       stats.combined_stacks / stats.stacks from cpu_signal_handler)     *)
(*   - scalene/scalene_profiler.py:885 cpu_signal_handler  (the writer     *)
(*       runs SYNCHRONOUSLY in signal context, not deferred)               *)
(*   - scalene/scalene_json.py:875 output_profiles                         *)
(*       `for stk,hits in stats.combined_stacks.items()`  (the reader)     *)
(*                                                                         *)
(* CPython semantics modeled:                                             *)
(*   - A Python-level signal handler runs between bytecode instructions    *)
(*     on the main thread; it cannot interleave *within* a single dict     *)
(*     mutation, but it CAN run between two iteration steps of the         *)
(*     output loop. We model each iteration step and each handler write    *)
(*     as one atomic action and let them interleave freely.                *)
(*   - Iterating a dict whose key-set changed since the iterator was       *)
(*     created raises RuntimeError("dictionary changed size during         *)
(*     iteration").  We model this as: if the live dict gains a key while  *)
(*     a *live-view* iteration is in progress, the iteration FAULTS.       *)
(*                                                                         *)
(* The flag UseSnapshot selects between the buggy code (iterate the live   *)
(* dict) and the fix (iterate list(dict.items()), a snapshot taken         *)
(* atomically at loop entry).                                              *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Keys,            \* universe of possible stack keys the handler may add
    UseSnapshot      \* TRUE  = list(stats....items()) fix; FALSE = buggy live iteration

ASSUME UseSnapshot \in BOOLEAN
ASSUME IsFiniteSet(Keys)

VARIABLES
    live,            \* the shared dict's key-set (stats.combined_stacks keys)
    outPC,           \* output thread program counter: "idle","iterating","done","fault"
    snap,            \* the snapshot the iterator walks (model of list(...items()))
    visited          \* keys the iterator has already emitted

vars == << live, outPC, snap, visited >>

Init ==
    /\ live = {}                 \* combined_stacks starts empty
    /\ outPC = "idle"
    /\ snap = {}
    /\ visited = {}

(*-----------------------------------------------------------------------*)
(* Writer: the CPU sampling signal handler appends a new stack key.       *)
(* Faithful to add_combined_stack (scalene_cpu_profiler.py:185).  It may  *)
(* fire at ANY time -- including while the output loop is mid-iteration.  *)
(*-----------------------------------------------------------------------*)
HandlerFire(k) ==
    /\ k \in Keys
    /\ k \notin live
    /\ live' = live \cup {k}
    /\ UNCHANGED << outPC, snap, visited >>

(*-----------------------------------------------------------------------*)
(* Output path: output_profiles begins iterating combined_stacks.         *)
(*   - Fix  (UseSnapshot): snapshot = current live key-set, atomically.   *)
(*   - Bug (~UseSnapshot): there is no snapshot; the loop reads the live  *)
(*       dict directly, so we track the key-set it was started against.   *)
(*-----------------------------------------------------------------------*)
OutputStart ==
    /\ outPC = "idle"
    /\ outPC' = "iterating"
    /\ snap' = live          \* snapshot at loop entry (fix) OR the "expected size" (bug baseline)
    /\ visited' = {}
    /\ UNCHANGED live

(*-----------------------------------------------------------------------*)
(* One iteration step.                                                    *)
(*  FIX: walk `snap` (decoupled from live); concurrent handler writes to  *)
(*       `live` are simply not seen -- never a fault.                      *)
(*  BUG: walk `live`; if `live` has grown since OutputStart (snap # live) *)
(*       CPython raises RuntimeError -> we transition to "fault".          *)
(*-----------------------------------------------------------------------*)
IterStepSnapshot ==
    /\ UseSnapshot
    /\ outPC = "iterating"
    /\ IF visited = snap
         THEN /\ outPC' = "done"
              /\ UNCHANGED << snap, visited >>
         ELSE /\ \E k \in (snap \ visited):
                   visited' = visited \cup {k}
              /\ UNCHANGED << snap, outPC >>
    /\ UNCHANGED live

IterStepLive ==
    /\ ~UseSnapshot
    /\ outPC = "iterating"
    /\ IF live # snap
         THEN /\ outPC' = "fault"          \* dictionary changed size during iteration
              /\ UNCHANGED << snap, visited >>
         ELSE IF visited = live
                THEN /\ outPC' = "done"
                     /\ UNCHANGED << snap, visited >>
                ELSE /\ \E k \in (live \ visited):
                          visited' = visited \cup {k}
                     /\ UNCHANGED << snap, outPC >>
    /\ UNCHANGED live

Next ==
    \/ \E k \in Keys: HandlerFire(k)
    \/ OutputStart
    \/ IterStepSnapshot
    \/ IterStepLive
    \/ (outPC \in {"done","fault"} /\ UNCHANGED vars)   \* stutter at end

Spec == Init /\ [][Next]_vars

(*-----------------------------------------------------------------------*)
(* PROPERTIES                                                            *)
(*-----------------------------------------------------------------------*)

(* Safety: the iterator never faults.  Expected to HOLD for the fix       *)
(* (UseSnapshot=TRUE) and to be VIOLATED for the bug (UseSnapshot=FALSE). *)
NoIterationFault == outPC # "fault"

(* When the snapshot iterator finishes, it has visited exactly the keys   *)
(* that existed at loop entry -- no key seen twice, none invented.        *)
SnapshotComplete ==
    (UseSnapshot /\ outPC = "done") => (visited = snap)

(* The snapshot iterator never observes a key that was not in the         *)
(* snapshot (no lost-update *into* the iteration; concurrent appends are  *)
(* correctly deferred to the next output cycle).                          *)
SnapshotSound ==
    UseSnapshot => (visited \subseteq snap)

TypeOK ==
    /\ live \subseteq Keys
    /\ snap \subseteq Keys
    /\ visited \subseteq Keys
    /\ outPC \in {"idle","iterating","done","fault"}
=============================================================================
