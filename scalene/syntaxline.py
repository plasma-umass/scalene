from rich.console import Console
from rich.segment import Segment
from typing import Any, Iterator, List


class SyntaxLine:
    def __init__(self, segments: List[Segment]):
        self.segments = segments

    def __rich_console__(
        self, console: Console, _options: Any
    ) -> Iterator[Segment]:
        yield from self.segments
