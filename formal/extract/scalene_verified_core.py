# ============================================================================
# GENERATED — DO NOT EDIT BY HAND.
#
# Extracted from formal/extract/ScaleneExtract.lean via LeanToPython
# (https://github.com/emeryberger/LeanToPython) from Lean defs that are PROVEN
# CORRECT in formal/lean/Scalene/{Attribution,SpaceSaving}.lean:
#   space_saving_step  -> capacity bound (SpaceSaving.step_withinCap/fold_withinCap)
#   c_time_ns/total_*  -> CPU Python/C split conservation (Attribution)
#   python_fraction_ppm-> result in [0,1]              (Attribution.pythonFraction_*)
#   python_bytes       -> python bytes <= total count  (Attribution.pythonBytes_le_count)
#   footprint_delta    -> footprint conservation        (Attribution.footprint_conserved)
#
# Regenerate:  (in a LeanToPython checkout, with ScaleneExtract.lean copied in)
#   lake env lean ScaleneExtract.lean > scalene_verified_core.py
#
# Used by tests/test_verified_space_saving.py as a verified reference ORACLE
# that the production scalene_utility._space_saving_increment is checked against.
# ============================================================================

# Generated from ScaleneVerified

from __future__ import annotations
from dataclasses import dataclass
import functools
from typing import Any, Callable

@dataclass
class isFalse:
    field_0: Any

@dataclass
class isTrue:
    field_0: Any

Decidable = isFalse | isTrue

@dataclass
class List_nil:
    pass

@dataclass
class List_cons:
    field_0: Any
    field_1: Any

List = List_nil | List_cons

# Lean: ScaleneVerified.cTimeNs
def c_time_ns(elapsed_ns: int, python_ns: int) -> int:
    _x_181 = python_ns <= elapsed_ns
    if _x_181:
        _x_190 = elapsed_ns - python_ns
        return _x_190
    else:
        _x_183 = 0
        return 0

# Lean: ScaleneVerified.totalTimeNs
def total_time_ns(elapsed_ns_0: int, python_ns_1: int) -> int:
    _x_196 = c_time_ns(elapsed_ns_0, python_ns_1)
    _x_197 = python_ns_1 + _x_196
    return _x_197

# Lean: ScaleneVerified.pythonFractionPpm
def python_fraction_ppm(python_count: int, c_count: int) -> int:
    _x_204 = python_count + c_count
    _x_205 = 0
    _x_208 = _x_204 == 0
    _x_209 = True
    if _x_208:
        return 0
    else:
        _x_218 = 1000000
        _x_221 = python_count * 1000000
        _x_222 = _x_221 // _x_204
        return _x_222

# Lean: ScaleneVerified.pythonBytes
def python_bytes(count: int, python_count_2: int, c_count_3: int) -> int:
    _x_232 = python_fraction_ppm(python_count_2, c_count_3)
    _x_233 = _x_232 * count
    _x_234 = 1000000
    _x_237 = _x_233 // 1000000
    return _x_237

# Lean: ScaleneVerified.footprintDelta
def footprint_delta(is_malloc: bool, count_4: int) -> int:
    _x_239 = True
    if is_malloc:
        return count_4
    else:
        _x_244 = -count_4
        return _x_244

# Lean: ScaleneVerified.hasKey
def has_key(t: list[tuple[int, int]], k: int) -> bool:
    def _f_252(p: tuple[int, int]):
        _x_250 = p[0]
        _x_251 = _x_250 == k
        return _x_251
    _x_253 = any(_f_252(x) for x in t)
    return _x_253

# Lean: ScaleneVerified.bump
def bump(t_5: list[tuple[int, int]], k_6: int) -> list[tuple[int, int]]:
    def _f_273(p_7: tuple[int, int]):
        _x_257 = p_7[0]
        _x_258 = _x_257 == k_6
        _x_259 = True
        if _x_258:
            _x_266 = p_7[1]
            _x_267 = 1
            _x_270 = _x_266 + 1
            _x_271 = (_x_257, _x_270)
            return _x_271
        else:
            return p_7
    _x_274 = [_f_273(x) for x in t_5]
    return _x_274

# Lean: ScaleneVerified.min2
def min2(a: int, b: int) -> int:
    _x_276 = a <= b
    if _x_276:
        return a
    else:
        return b

# Lean: ScaleneVerified.minCount
def min_count(x_281: list[tuple[int, int]]) -> int:
    def _f_285():
        _x_282 = 0
        return 0
    _alt_286 = _f_285
    def _f_288(p_8: tuple[int, int]):
        _x_287 = p_8[1]
        return _x_287
    _alt_289 = _f_288
    def _f_294(p_9: tuple[int, int], q: tuple[int, int], r: list[tuple[int, int]]):
        _x_290 = p_9[1]
        _x_291 = [q] + r
        _x_292 = min_count(_x_291)
        _x_293 = min2(_x_290, _x_292)
        return _x_293
    _alt_295 = _f_294
    if len(x_281) == 0:
        _x_297 = _alt_286()
        return _x_297
    else:
        head_298 = x_281[0]
        tail_299 = x_281[1:]
        if len(tail_299) == 0:
            _x_300 = _alt_289(head_298)
            return _x_300
        else:
            head_301 = tail_299[0]
            tail_302 = tail_299[1:]
            _x_303 = _alt_295(head_298, head_301, tail_302)
            return _x_303

# Lean: ScaleneVerified.dropFirstWithCount
def drop_first_with_count(x_307: list[tuple[int, int]], x_308: int) -> list[tuple[int, int]]:
    def _f_311(x_309: int):
        _x_310 = []
        return _x_310
    _alt_312 = _f_311
    def _f_324(p_10: tuple[int, int], rest: list[tuple[int, int]], m: int):
        _x_315 = p_10[1]
        _x_316 = _x_315 == m
        _x_317 = True
        if _x_316:
            return rest
        else:
            _x_320 = drop_first_with_count(rest, m)
            _x_321 = [p_10] + _x_320
            return _x_321
    _alt_325 = _f_324
    if len(x_307) == 0:
        _x_326 = _alt_312(x_308)
        return _x_326
    else:
        head_327 = x_307[0]
        tail_328 = x_307[1:]
        _x_329 = _alt_325(head_327, tail_328, x_308)
        return _x_329

# Lean: ScaleneVerified.spaceSavingStep
def space_saving_step(cap: int, t_11: list[tuple[int, int]], k_12: int) -> list[tuple[int, int]]:
    _x_332 = has_key(t_11, k_12)
    _x_333 = True
    if _x_332:
        _x_358 = bump(t_11, k_12)
        return _x_358
    else:
        _x_336 = len(t_11)
        _x_337 = _x_336 < cap
        if _x_337:
            _x_351 = 1
            _x_354 = (k_12, 1)
            _x_355 = [_x_354] + t_11
            return _x_355
        else:
            _x_339 = min_count(t_11)
            _x_343 = 1
            _x_346 = _x_339 + 1
            _x_347 = (k_12, _x_346)
            _x_348 = drop_first_with_count(t_11, _x_339)
            _x_349 = [_x_347] + _x_348
            return _x_349


