import dis
import sys
from functools import lru_cache
from types import CodeType
from typing import FrozenSet, List, Optional, Set, Tuple

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

    # All jump opcodes (absolute and relative).  dis.hasjabs and
    # dis.hasjrel are lists of opcode *integers* on all Python versions.
    __jump_opcodes: FrozenSet[int] = frozenset(dis.hasjabs) | frozenset(dis.hasjrel)

    @staticmethod
    @lru_cache(maxsize=None)
    def get_loop_body_lines(code: CodeType, lineno: int) -> Optional[Tuple[int, ...]]:
        """Return all lines of the innermost loop whose first body line is *lineno*.

        When CPython's eval-breaker fires at a backward jump instruction
        the signal handler sees f_lineno equal to the first body line of
        the loop.  This method detects that situation and returns a tuple
        of all distinct source lines in the loop (condition + body) so the
        caller can redistribute the sample evenly.

        Returns ``None`` if *lineno* is not the first body line of any loop.
        """
        best: Optional[Tuple[int, ...]] = None
        all_instrs = ScaleneFuncUtils._instructions_with_lines(code)

        for instr, _ in all_instrs:
            # Detect any backward jump (loop back-edge).
            # On Python < 3.11, while loops may use POP_JUMP_IF_TRUE
            # for backward jumps; on 3.11+, JUMP_BACKWARD is used.
            if instr.opcode not in ScaleneFuncUtils.__jump_opcodes:
                continue
            target = instr.argval
            if not isinstance(target, int) or target >= instr.offset:
                continue  # not a backward jump

            # Collect distinct source lines in [target, instr.offset]
            # and check whether any CALL instructions appear in the body.
            lines: List[int] = []
            seen: Set[int] = set()
            has_call = False
            for i2, line in all_instrs:
                if i2.offset < target:
                    continue
                if i2.offset > instr.offset:
                    break
                if line is not None and line not in seen:
                    lines.append(line)
                    seen.add(line)
                if i2.opcode in ScaleneFuncUtils.__call_opcodes:
                    has_call = True

            # Need at least condition + one body line
            if len(lines) < 2:
                continue

            # Skip loops with function calls — their lines have
            # non-uniform cost, so even redistribution would distort
            # the profile.  Let the normal C-time attribution handle
            # these instead.
            if has_call:
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
        """Get the line number from an instruction across Python versions.

        On Python >= 3.13, ``line_number`` is set on every instruction.
        On Python < 3.13, ``starts_line`` is ``int | None`` but only set
        on the *first* instruction of each source line.  Callers that need
        a line for every instruction should track the current line across
        the instruction stream (see ``_instructions_with_lines``).
        """
        if sys.version_info >= (3, 13):
            return instr.line_number
        return instr.starts_line

    @staticmethod
    def _instructions_with_lines(
        code: CodeType,
    ) -> List[Tuple[dis.Instruction, Optional[int]]]:
        """Return instructions paired with their effective line number.

        On Python < 3.13, ``starts_line`` is only set on the first
        instruction of each source line.  This helper propagates the
        line forward so every instruction has a line number.
        """
        result: List[Tuple[dis.Instruction, Optional[int]]] = []
        current_line: Optional[int] = None
        for instr in dis.get_instructions(code):
            line = ScaleneFuncUtils._instr_line(instr)
            if line is not None:
                current_line = line
            result.append((instr, current_line))
        return result

    @staticmethod
    @lru_cache(maxsize=None)
    def find_preceding_call_line(code: CodeType, bytei: ByteCodeIndex) -> Optional[int]:
        """Find the line of the nearest CALL instruction preceding *bytei*.

        Walks backward through the instruction stream looking for the last
        CALL opcode that appears before the given bytecode index.  Returns
        its source line, or ``None`` if no preceding CALL is found.
        """
        last_call_line: Optional[int] = None
        for instr, line in ScaleneFuncUtils._instructions_with_lines(code):
            if instr.offset >= bytei:
                break
            if instr.opcode in ScaleneFuncUtils.__call_opcodes and line is not None:
                last_call_line = line
        return last_call_line
