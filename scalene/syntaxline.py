class SyntaxLine:
    def __init__(self, segments):
        self.segments = segments

    def __rich_console__(self, console, options):
        yield from self.segments

