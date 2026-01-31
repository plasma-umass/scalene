import dis
import sys
from functools import lru_cache
from types import CodeType
from typing import FrozenSet, Optional

from scalene.scalene_statistics import ByteCodeIndex


class ScaleneFuncUtils:
    """Utility class to determine whether a bytecode corresponds to function calls."""

    # We use these in is_call_function to determine whether a
    # particular bytecode is a function call.  We use this to
    # distinguish between Python and native code execution when
    # running in threads.
    __call_opcodes: FrozenSet[int] = frozenset(
        {
            dis.opmap[op_name]
            for op_name in dis.opmap
            if op_name.startswith("CALL") and not op_name.startswith("CALL_INTRINSIC")
        }
    )

    @staticmethod
    @lru_cache(maxsize=None)
    def is_call_function(code: CodeType, bytei: ByteCodeIndex) -> bool:
        """Returns true iff the bytecode at the given index is a function call."""
        return any(
            (ins.offset == bytei and ins.opcode in ScaleneFuncUtils.__call_opcodes)
            for ins in dis.get_instructions(code)
        )

    # Backward-jump opcodes used for loop detection.
    __backward_jump_opcodes: FrozenSet[str] = frozenset(
        name for name in dis.opmap
        if name in ("JUMP_BACKWARD", "JUMP_BACKWARD_NO_INTERRUPT", "JUMP_ABSOLUTE")
    )

    @staticmethod
    @lru_cache(maxsize=None)
    def get_loop_body_lines(code: CodeType, lineno: int) -> Optional[tuple[int, ...]]:
        """Return all lines of the innermost loop whose first body line is *lineno*.

        When CPython's eval-breaker fires at a JUMP_BACKWARD instruction
        the signal handler sees f_lineno equal to the first body line of
        the loop.  This method detects that situation and returns a tuple
        of all distinct source lines in the loop (condition + body) so the
        caller can redistribute the sample evenly.

        Returns ``None`` if *lineno* is not the first body line of any loop.
        """
        best: Optional[tuple[int, ...]] = None

        for instr in dis.get_instructions(code):
            op_name = instr.opname
            if op_name not in ScaleneFuncUtils.__backward_jump_opcodes:
                continue

            # Determine target offset for backward jump
            if op_name == "JUMP_ABSOLUTE":
                target = instr.argval
                if target >= instr.offset:
                    continue  # forward jump, skip
            else:
                target = instr.argval  # dis resolves to absolute offset

            if target >= instr.offset:
                continue  # not actually backward

            # Collect distinct source lines in [target, instr.offset]
            lines: list[int] = []
            seen: set[int] = set()
            for i2 in dis.get_instructions(code):
                if i2.offset < target:
                    continue
                if i2.offset > instr.offset:
                    break
                line = ScaleneFuncUtils._instr_line(i2)
                if line is not None and line not in seen:
                    lines.append(line)
                    seen.add(line)

            # Need at least condition + one body line
            if len(lines) < 2:
                continue

            first_body_line = lines[1]
            if first_body_line != lineno:
                continue

            loop_span = instr.offset - target
            # Pick innermost (smallest span) matching loop
            if best is None or loop_span < len(best):
                best = tuple(lines)

        return best

    @staticmethod
    def _instr_line(instr: dis.Instruction) -> Optional[int]:
        """Get the line number from an instruction across Python versions."""
        if sys.version_info >= (3, 14):
            return instr.line_number  # type: ignore[attr-defined]
        return instr.starts_line  # type: ignore[return-value]

    @staticmethod
    @lru_cache(maxsize=None)
    def find_preceding_call_line(code: CodeType, bytei: ByteCodeIndex) -> Optional[int]:
        """Find the line of the nearest CALL instruction preceding *bytei*.

        Walks backward through the instruction stream looking for the last
        CALL opcode that appears before the given bytecode index.  Returns
        its source line, or ``None`` if no preceding CALL is found.
        """
        last_call_line: Optional[int] = None
        for instr in dis.get_instructions(code):
            if instr.offset >= bytei:
                break
            if instr.opcode in ScaleneFuncUtils.__call_opcodes:
                line = ScaleneFuncUtils._instr_line(instr)
                if line is not None:
                    last_call_line = line
        return last_call_line
