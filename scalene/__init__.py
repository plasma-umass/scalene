# Jupyter support

try:
    from IPython.core.magic import (Magics, magics_class, line_magic, cell_magic, line_cell_magic)
    from IPython.core.page import page
    from scalene.scalene_arguments import ScaleneArguments
    import os
    import sys
    import tempfile
    import textwrap
    
    @magics_class
    class ScaleneMagics(Magics):
        @cell_magic
        def scalene(self, line, cell=None) -> None:
            from scalene import scalene_profiler
            if line:
                sys.argv = ["scalene"]
                sys.argv.extend(line.split(" "))
                (args, left) = scalene_profiler.Scalene.parse_args()
            else:
                args = ScaleneArguments()
            args.cpu_only = True # full Scalene is not yet working, force to use CPU-only mode
            if cell:
                # Create a temporary file to hold the supplied code.
                code = cell
                tmpfile = tempfile.NamedTemporaryFile(mode="w+", delete=False, prefix="scalene_", suffix=".py")
                tmpfile.write(code)
                tmpfile.close()
                # For now, only profile the temporary file (that is, the current cell).
                args.profile_only = os.path.basename(tmpfile.name)
                scalene_profiler.Scalene.run_profiler(args, [tmpfile.name])

    def load_ipython_extension(ip):
        ip.register_magics(ScaleneMagics)
except:
    pass

