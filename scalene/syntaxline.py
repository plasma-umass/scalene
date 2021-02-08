from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from typing import Any, Generator, List


class SyntaxLine:
    def __init__(self, segments: List[Segment]):
        self.segments = segments

    def __rich_console__(
        self, console: Console, options: Any
    ) -> Generator[Any, Any, Segment]:
        yield from self.segments
