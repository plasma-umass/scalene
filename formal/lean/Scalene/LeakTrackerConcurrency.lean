/-
  AUDIT (part 2): does `frees ≤ allocs` survive the CONCURRENCY and FORK that
  `LeakTrackerAudit.lean` abstracted away?

  `LeakTrackerAudit` proved the invariant for a single *sequential* event stream
  (`run`). But in the code the two increment sites run under a specific
  concurrency discipline, and the state is duplicated across `fork`. The handoff
  (HANDOFF.md §6 bullet 3, §7 step 2) flags this as the biggest "assumed-not-
  proven" gap: "faithfulness under the sig-queue thread vs. main-thread
  interleaving and across fork is NOT proven. A race there could break
  `frees ≤ allocs`." This file discharges that gap — and, per the §0 method,
  proves the discipline is *necessary*, not merely present.

  ── WHAT THE CODE ACTUALLY DOES (verified while writing this) ──────────────────
  * Both increment sites are in ONE function, `process_malloc_free_samples`
    (scalene_memory_profiler.py): the free-credit at :236 and the alloc-credit at
    :401 are two spots in the same call. There is no point at which one runs
    "half done" while the other starts.
  * That function runs on a single dedicated sig-queue thread, and
    `ScaleneSigQueue.run` holds an `RLock` (`with self.lock:`,
    scalene_sigqueue.py:48) around each `self.process(*item)`. So each whole
    invocation is a CRITICAL SECTION — atomic w.r.t. every other invocation.
  * The only other caller is the shutdown drain (scalene_profiler.py:1591). It
    runs after `stop()` → `_disable_signals()` → `stop_signal_queues()`, which
    JOINS the sig-queue thread (scalene_sigqueue.py:37). So the drain never
    overlaps the thread — it is one more atomic step in the same sequence.
  * Across `fork`: `before_fork` (scalene_profiler.py:541) stops/joins the queue
    (quiesce); `after_fork_in_child` (:522) calls `stats.clear()`, which resets
    `leak_score` AND `last_malloc_triggered` TOGETHER (scalene_statistics.py:
    456-457) while the tracker is quiescent.

  ── WHAT WE PROVE ──────────────────────────────────────────────────────────────
  (A) INTERLEAVING SAFETY. If each `process_malloc_free_samples` call is atomic
      (one `step`), then EVERY interleaving of the sig-queue thread's steps with
      the main-thread drain's steps preserves the invariant — thread order is
      irrelevant. This is what the RLock buys us. (`interleave_preserves_inv`)
  (B) ATOMICITY IS NECESSARY. If a free-credit could apply WITHOUT its disarm
      (the lost-disarm race that dropping the lock would permit), the invariant
      genuinely breaks: two torn frees double-credit one armed trigger, yielding
      `frees = allocs + 1`. So the RLock is load-bearing, not decorative.
      (`torn_free_breaks_inv`)
  (C) FORK RESET IS SAFE — AND MUST RESET BOTH FIELDS. The full reset that
      `clear()` performs lands back in the initial state, so Inv holds
      (`fork_reset_inv`). But a *partial* reset that zeroed the counters while
      leaving the trigger armed (i.e. clearing `leak_score` but forgetting
      `last_malloc_triggered`, scalene_statistics.py:457) breaks Inv — the next
      free credits a line with zero allocs. So resetting both together is
      necessary. (`partial_fork_reset_breaks_inv`)

  Together with `LeakTrackerAudit.run_frees_le_allocs`, this closes the loop:
  the divide-by-zero-safety of scalene_leak_analysis.py:31 holds not just for a
  sequential trace but for the real concurrent + forking execution — *provided*
  the two disciplines the code implements (RLock atomicity, joint fork reset)
  are in place. Both are shown necessary here.
-/
import Mathlib
import Scalene.LeakTrackerAudit

namespace Scalene.LeakTrackerConcurrency

open Scalene.LeakTrackerAudit

variable {Line : Type} [DecidableEq Line]

/-! ## Reusable lemma: `run` preserves the invariant over any event list.

    `LeakTrackerAudit` proved this inline inside `run_frees_le_allocs`; we pull
    it out because the interleaving argument needs it directly. -/

theorem run_preserves_inv (t : Tracker Line) (es : List (Ev Line)) (h : Inv t) :
    Inv (run t es) := by
  induction es generalizing t with
  | nil => simpa [run] using h
  | cons e es ih => simp only [run]; exact ih _ (step_preserves_inv t e h)

/-! ## (A) Interleaving safety

    The sig-queue thread produces a sequence of atomic steps; the main-thread
    drain produces its own (here, at most one). Because each step is atomic (the
    RLock), a concurrent execution is exactly *some* interleaving of the two
    step sequences. We model interleaving inductively and prove Inv survives
    *any* interleaving — i.e. the result does not depend on how the scheduler
    races the two threads. -/

/-- `Interleave as bs cs`: `cs` is a merge of `as` and `bs` that preserves the
    internal order of each — the standard shuffle relation. Each constructor
    commits one whole `step` from one thread, reflecting step-level atomicity. -/
inductive Interleave : List (Ev Line) → List (Ev Line) → List (Ev Line) → Prop
  | nil : Interleave [] [] []
  | left  {a : Ev Line} {as bs cs} :
      Interleave as bs cs → Interleave (a :: as) bs (a :: cs)
  | right {b : Ev Line} {as bs cs} :
      Interleave as bs cs → Interleave as (b :: bs) (b :: cs)

/-- **Every interleaving of the two threads' atomic steps preserves the
    invariant.** This is the payoff of the RLock: no matter how the sig-queue
    thread and the shutdown drain are scheduled relative to each other,
    `frees ≤ allocs` is maintained. -/
theorem interleave_preserves_inv {as bs cs : List (Ev Line)}
    (_hInt : Interleave as bs cs) (t : Tracker Line) (h : Inv t) :
    Inv (run t cs) :=
  -- Once steps are atomic, an interleaving is just *some* event list, and `run`
  -- preserves Inv over any event list. The scheduler cannot help itself to a
  -- sub-step tear — that is exactly what atomicity forbids (and what (B) shows
  -- would otherwise be catastrophic).
  run_preserves_inv t cs h

/-- Corollary: the concrete shape in the code — the sig-queue thread runs a
    batch of steps `sig`, then the joined main thread runs its drain steps
    `drain` — is one interleaving, hence safe. -/
theorem sigqueue_then_drain_safe (sig drain : List (Ev Line)) :
    Inv (run (⟨fun _ => ⟨0, 0⟩, none⟩ : Tracker Line) (sig ++ drain)) :=
  run_preserves_inv _ _ inv_init

/-! ## (B) Atomicity is necessary: the lost-disarm race breaks the invariant.

    Model what dropping the RLock would allow: a free-credit that increments
    `frees` but does NOT disarm the trigger (because a second invocation reads
    `last_malloc_triggered` before the first writes the disarm). Two such torn
    frees on the same armed trigger both credit a free. -/

/-- A "torn" free: credits a free to the armed line but FAILS to disarm — the
    write `armed := none` is lost to a concurrent reader. This is precisely the
    interleaving the RLock prevents. -/
def tornFree (t : Tracker Line) : Tracker Line :=
  match t.armed with
  | some ℓ =>
      { count := fun k => if k = ℓ then ⟨(t.count k).allocs, (t.count k).frees + 1⟩
                          else t.count k,
        armed := t.armed }        -- BUG vs. `step`: trigger left armed
  | none => t

/-- **Without atomic disarm, `frees ≤ allocs` is violated.** Starting from a
    legitimate armed state (one alloc credited, trigger owed a free — Inv holds),
    two torn frees produce `frees = 2 > 1 = allocs`. So the invariant that keeps
    the leak-score denominator positive genuinely depends on the disarm being
    atomic with the free credit; the RLock is load-bearing. -/
theorem torn_free_breaks_inv :
    ∃ t : Tracker ℕ, Inv t ∧ ¬ Inv (tornFree (tornFree t)) := by
  -- Armed at line 0, which has been credited one alloc and owes one free.
  refine ⟨⟨fun k => if k = 0 then ⟨1, 0⟩ else ⟨0, 0⟩, some 0⟩, ?_, ?_⟩
  · -- Inv holds initially: frees ≤ allocs everywhere, and armed line owes a free.
    constructor
    · intro ℓ; by_cases hℓ : ℓ = 0 <;> simp [hℓ]
    · intro ℓ h; simp only [Option.some.injEq] at h; subst h; simp
  · -- After two torn frees, line 0 has allocs = 1, frees = 2 ⇒ ¬ (frees ≤ allocs).
    intro hInv
    have hle := hInv.1 0
    simp [tornFree] at hle

/-! ## (C) Fork reset is safe — and both fields must be reset together.

    `after_fork_in_child` → `stats.clear()` resets the tracker to empty. -/

/-- The full fork reset the code performs (`clear()` zeros `leak_score` *and*
    `last_malloc_triggered`, scalene_statistics.py:456-457). -/
def forkReset (_t : Tracker Line) : Tracker Line := ⟨fun _ => ⟨0, 0⟩, none⟩

/-- **The child process starts safe.** After fork, whatever the parent's state,
    the reset lands in the initial tracker, so Inv holds and the sequential proof
    resumes cleanly in the child. -/
theorem fork_reset_inv (t : Tracker Line) : Inv (forkReset t) :=
  inv_init

/-- A hypothetical *partial* reset that zeroed the counters but forgot to clear
    the armed trigger — i.e. `leak_score.clear()` without
    scalene_statistics.py:457. -/
def partialForkReset (t : Tracker Line) : Tracker Line :=
  ⟨fun _ => ⟨0, 0⟩, t.armed⟩

/-- **Both fields must be reset together.** If the fork reset zeroed the counts
    but left the trigger armed, the child violates Inv immediately: the armed
    line owes a free it can never have room for (0 allocs), so the first
    post-fork free would push `frees` past `allocs`. This is why
    scalene_statistics.py:457 resets `last_malloc_triggered` alongside
    `leak_score`. -/
theorem partial_fork_reset_breaks_inv :
    ∃ t : Tracker ℕ, ¬ Inv (partialForkReset t) := by
  -- Parent had line 0 armed when the fork hit.
  refine ⟨⟨fun _ => ⟨0, 0⟩, some 0⟩, ?_⟩
  intro hInv
  -- Second conjunct demands the armed line have frees < allocs, i.e. 0 < 0.
  have h := hInv.2 0 rfl
  simp only [partialForkReset] at h
  omega

end Scalene.LeakTrackerConcurrency
