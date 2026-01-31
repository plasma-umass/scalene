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
