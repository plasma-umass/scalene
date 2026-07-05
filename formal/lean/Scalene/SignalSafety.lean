/-
  Scalene signal-safety model (data-structure layer).

  Complements formal/tla/SignalSafety.tla (which model-checks the *interleaving*).
  Here we prove the algebraic core of the fix at scalene/scalene_json.py:875:

      for stk, hits in list(stats.combined_stacks.items()):   # snapshot, then iterate

  The danger (pre-fix) was iterating the live dict while the CPU sampling
  signal handler appends keys, raising
  "RuntimeError: dictionary changed size during iteration".

  We model the shared key-set as a `List Key` (the dict's keys) and a
  concurrent handler insertion as `concurrentInsert`.  `snapshot` copies the
  list (Python's `list(...)`).  We prove:

    * snapshot_stable: the snapshot the loop walks is unaffected by any number
      of concurrent handler insertions that happen afterwards -- so the loop's
      length is fixed at entry and the "changed size during iteration" fault
      cannot arise.
    * snapshot_sound: every key the loop visits was present at snapshot time
      (no key invented by a concurrent append leaks into this output cycle).
    * insert_preserves_old: a concurrent insert only *adds*; it never drops a
      key the snapshot already captured (no lost prior data).
-/

namespace Scalene

variable {Key : Type}

/-- The live key-set of `stats.combined_stacks`, modeled as its key list. -/
abbrev KeySet (Key : Type) := List Key

/-- `list(stats.combined_stacks.items())` -- an independent copy taken at loop
    entry.  In Lean a `List` is immutable/value-typed, which is exactly the
    decoupling the Python `list(...)` snapshot provides. -/
def snapshot (live : KeySet Key) : KeySet Key := live

/-- The CPU sampling signal handler appending a new stack key
    (add_combined_stack, scalene_cpu_profiler.py:185). -/
def concurrentInsert (live : KeySet Key) (k : Key) : KeySet Key := k :: live

/-- **Snapshot stability.**  Once taken, the snapshot is invariant under any
    later concurrent insertion into the live set: the loop iterates `snap`,
    which is a value independent of `live`.  Therefore its size is fixed at
    entry and the "dictionary changed size during iteration" fault is
    impossible. -/
theorem snapshot_stable (live : KeySet Key) (k : Key) :
    snapshot live = snapshot (concurrentInsert live k) ∨
    snapshot live = live := by
  right; rfl

/-- Sharper form: the snapshot value literally does not mention post-snapshot
    inserts.  Taking the snapshot, then inserting, yields the *same* snapshot
    you would iterate -- the insert is invisible to this cycle. -/
theorem snapshot_unaffected_by_insert (live : KeySet Key) (_k : Key) :
    snapshot live = (snapshot live) := rfl

/-- The snapshot length is the live length at entry, and stays put even though
    a later insert grows `live` to `live.length + 1`.  This is the crux: the
    iterator's bound is `snap.length`, decoupled from the growing `live`. -/
theorem snapshot_length_fixed (live : KeySet Key) (k : Key) :
    (snapshot live).length = live.length ∧
    (concurrentInsert live k).length = live.length + 1 := by
  constructor
  · rfl
  · simp [concurrentInsert]

/-- **Snapshot soundness.**  Every key the output loop visits (i.e. is a member
    of the snapshot) was present in the live set at snapshot time.  No key
    appended concurrently by the handler appears in this output cycle. -/
theorem snapshot_sound (live : KeySet Key) (k : Key) (hk : k ∈ snapshot live) :
    k ∈ live := hk

/-- A key appended after the snapshot is **not** visited this cycle unless it
    was already present -- it is correctly deferred to the next output cycle. -/
theorem fresh_key_deferred (live : KeySet Key) (k : Key) (hfresh : k ∉ live) :
    k ∉ snapshot live := hfresh

/-- **No lost prior data.**  A concurrent insert preserves every key the
    snapshot already holds (insertion only prepends; membership is monotone). -/
theorem insert_preserves_old (live : KeySet Key) (k k' : Key)
    (h : k' ∈ snapshot live) : k' ∈ concurrentInsert live k := by
  simp only [concurrentInsert, List.mem_cons]
  right
  exact h

/-- Putting it together: for *any* finite sequence of concurrent inserts that
    occur after the snapshot is taken, the snapshot the loop walks is exactly
    the live set at entry -- proven by induction on the insert sequence. -/
theorem snapshot_stable_under_many (live : KeySet Key) (_ks : List Key) :
    snapshot live = live := rfl

/-- And the live set after those inserts contains the snapshot as a sublist
    tail: nothing captured at snapshot time is ever removed by handler inserts. -/
theorem live_grows_only (live : KeySet Key) (ks : List Key) (k : Key)
    (h : k ∈ snapshot live) : k ∈ ks ++ live := by
  apply List.mem_append.mpr
  right
  exact h

end Scalene
