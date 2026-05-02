"""Pydantic-level validation of the combined_stacks / memory_stacks /
combined_stacks_timeline sections of the Scalene profile JSON.

These sections used to be declared as ``List[List[Any]]`` (or not declared
at all) in ``ScaleneJSONSchema``, so pydantic happily passed through any
shape the emitter produced. P5 / P6 tightened the schema to reject:

  - combined_stacks entries whose inner frames are missing fields.
  - combined_stacks_timeline events with negative counts or non-numeric
    timestamps.
  - memory_stacks entries with a negative MB weight.

These tests are the positive + negative fixtures for that contract.
"""

import pytest
from pydantic import ValidationError

from scalene.scalene_json import ScaleneJSONSchema


def _minimal_profile(**overrides):
    """Build the minimum top-level profile dict that passes
    ScaleneJSONSchema validation. Tests extend it with the section
    under test."""
    base = {
        "alloc_samples": 0,
        "args": [],
        "async_profile": False,
        "elapsed_time_sec": 1.0,
        "start_time_absolute": 0.0,
        "start_time_perf": 0.0,
        "entrypoint_dir": "/tmp",
        "filename": "demo.py",
        "files": {},
        "gpu": False,
        "gpu_device": "",
        "growth_rate": 0.0,
        "max_footprint_fname": None,
        "max_footprint_lineno": None,
        "max_footprint_mb": 0.0,
        "max_footprint_python_fraction": 0.0,
        "memory": False,
        "program": "demo.py",
        "samples": [],
        "stacks": [],
    }
    base.update(overrides)
    return base


def _py_frame(line=1, filename="/app/work.py", name="f"):
    return {
        "kind": "py",
        "display_name": name,
        "filename_or_module": filename,
        "line": line,
        "ip": None,
        "offset": None,
    }


def _native_frame(ip=0x1000, offset=0, module="/lib/x.so", sym="g"):
    return {
        "kind": "native",
        "display_name": sym,
        "filename_or_module": module,
        "line": None,
        "ip": ip,
        "offset": offset,
    }


class TestCombinedStacksValidation:
    def test_valid_combined_stacks_accepted(self):
        """A well-formed combined_stacks entry validates cleanly."""
        profile = _minimal_profile(
            combined_stacks=[
                [
                    [_py_frame(line=10), _native_frame()],
                    3,
                ]
            ]
        )
        schema = ScaleneJSONSchema.model_validate(profile)
        assert len(schema.combined_stacks) == 1

    def test_missing_kind_rejected(self):
        """A py frame missing its discriminator ``kind`` must fail."""
        bad_frame = _py_frame()
        bad_frame.pop("kind")
        profile = _minimal_profile(combined_stacks=[[[bad_frame], 1]])
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)

    def test_native_frame_missing_ip_rejected(self):
        """Native frames must carry an integer ``ip``."""
        bad = _native_frame()
        bad.pop("ip")
        profile = _minimal_profile(combined_stacks=[[[bad], 1]])
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)

    def test_negative_hits_rejected(self):
        """The per-entry hit count must be non-negative."""
        profile = _minimal_profile(
            combined_stacks=[[[_py_frame()], -1]],
        )
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)

    def test_code_line_no_longer_required(self):
        """P5 removed code_line from py frames; schema must accept its
        absence. (Legacy profiles that still carry code_line also pass
        because pydantic ignores unknown extra fields by default.)"""
        frame_without = _py_frame()  # no code_line
        frame_with = {**_py_frame(), "code_line": "x = 1"}
        profile = _minimal_profile(
            combined_stacks=[[[frame_without, frame_with], 1]]
        )
        schema = ScaleneJSONSchema.model_validate(profile)
        assert len(schema.combined_stacks) == 1


class TestCombinedStacksTimelineValidation:
    def test_valid_timeline_event_accepted(self):
        profile = _minimal_profile(
            combined_stacks_timeline=[
                {"t_sec": 0.0, "stack_index": 0, "count": 1}
            ]
        )
        schema = ScaleneJSONSchema.model_validate(profile)
        assert len(schema.combined_stacks_timeline) == 1

    def test_negative_count_rejected(self):
        profile = _minimal_profile(
            combined_stacks_timeline=[
                {"t_sec": 0.0, "stack_index": 0, "count": -1}
            ]
        )
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)

    def test_negative_t_sec_rejected(self):
        profile = _minimal_profile(
            combined_stacks_timeline=[
                {"t_sec": -1.0, "stack_index": 0, "count": 1}
            ]
        )
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)

    def test_non_numeric_t_sec_rejected(self):
        profile = _minimal_profile(
            combined_stacks_timeline=[
                {"t_sec": "soon", "stack_index": 0, "count": 1}
            ]
        )
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)


class TestMemoryStacksValidation:
    def test_valid_memory_stack_entry_accepted(self):
        profile = _minimal_profile(
            memory_stacks=[[[_py_frame()], 3.25]],
        )
        schema = ScaleneJSONSchema.model_validate(profile)
        assert len(schema.memory_stacks) == 1

    def test_negative_mb_rejected(self):
        """Memory weight is bytes attributed; negative MB is nonsensical."""
        profile = _minimal_profile(
            memory_stacks=[[[_py_frame()], -1.0]],
        )
        with pytest.raises(ValidationError):
            ScaleneJSONSchema.model_validate(profile)


class TestNativeStacksDropped:
    def test_schema_does_not_require_native_stacks(self):
        """P6 dropped the ``native_stacks`` JSON section. A profile that
        doesn't emit it must still validate. (Profiles that DO emit
        ``native_stacks`` — e.g. from a pre-P6 Scalene — also pass because
        pydantic ignores unknown extras by default.)"""
        profile = _minimal_profile()
        assert "native_stacks" not in profile
        schema = ScaleneJSONSchema.model_validate(profile)
        # Not a declared attribute on the schema either.
        assert not hasattr(schema, "native_stacks")
