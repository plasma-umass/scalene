import dis
import sys
from functools import lru_cache
from types import CodeType
from typing import FrozenSet

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
            if op_name.startswith("CALL")
            and not op_name.startswith("CALL_INTRINSIC")
        }
    )

    @staticmethod
    @lru_cache(maxsize=None)
    def is_call_function(code: CodeType, bytei: ByteCodeIndex) -> bool:
        """Returns true iff the bytecode at the given index is a function call."""
        return any(
            (
                ins.offset == bytei
                and ins.opcode in ScaleneFuncUtils.__call_opcodes
            )
            for ins in dis.get_instructions(code)
        )
