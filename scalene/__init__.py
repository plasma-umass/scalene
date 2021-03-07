# Jupyter support

try:
    from IPython.core.magic import (Magics, magics_class, line_magic, cell_magic, line_cell_magic)
    from IPython.core.page import page
    from scalene import scalene_profiler
    from scalene.scalene_arguments import ScaleneArguments
    from typing import Any
    import os
    import sys
    import tempfile
    import textwrap
    
    @magics_class
    class ScaleneMagics(Magics): # type: ignore

        def run_code(self, args: ScaleneArguments, code: str) -> None:
            # Create a temporary file to hold the supplied code.
            tmpfile = tempfile.NamedTemporaryFile(mode="w+", delete=False, prefix="scalene_profile_", suffix=".py")
            tmpfile.write(code)
            tmpfile.close()
            args.cpu_only = True # full Scalene is not yet working, force to use CPU-only mode
            scalene_profiler.Scalene.run_profiler(args, [tmpfile.name])
           
        @line_cell_magic
        def scalene(self, line : str, cell : str = "") -> None:
            if line:
                sys.argv = ["scalene"]
                sys.argv.extend(line.split(" "))
                (args, left) = scalene_profiler.Scalene.parse_args()
            else:
                args = ScaleneArguments()
            if cell:
                self.run_code(args, cell) # type: ignore
                
        @line_magic
        def scrun(self, line: str = "") -> None:
            from scalene import scalene_profiler
            if line:
                sys.argv = ["scalene"]
                sys.argv.extend(line.split(" "))
                (args, left) = scalene_profiler.Scalene.parse_args()
                self.run_code(args, (" ").join(left)) # type: ignore

    def load_ipython_extension(ip: Any) -> None:
        ip.register_magics(ScaleneMagics)
        
except:
    pass

