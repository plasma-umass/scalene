import sys
import sysconfig
from os import environ, path
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.extension import Extension

# needed for isolated environment
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from scalene.scalene_config import scalene_version

sys.path.pop(0)


if sys.platform == "darwin":
    import sysconfig

    mdt = "MACOSX_DEPLOYMENT_TARGET"
    target = environ[mdt] if mdt in environ else sysconfig.get_config_var(mdt)
    # target >= 10.9 is required for gcc/clang to find libstdc++ headers
    if [int(n) for n in target.split(".")] < [10, 9]:
        from os import execve

        newenv = environ.copy()
        newenv[mdt] = "10.9"
        execve(sys.executable, [sys.executable] + sys.argv, newenv)


def compiler_archs(compiler: str):
    """Discovers what platforms the given compiler supports; intended for MacOS use"""
    import subprocess
    import tempfile

    print(f"Compiler: {compiler}")
    arch_flags = []

    # see also the architectures tested for in .github/workflows/build-and-upload.yml
    for arch in ["x86_64", "arm64", "arm64e"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            cpp = Path(tmpdir) / "test.cxx"
            cpp.write_text("int main() {return 0;}\n")
            out = Path(tmpdir) / "a.out"
            p = subprocess.run(
                [compiler, "-arch", arch, str(cpp), "-o", str(out)], capture_output=True
            )
            if p.returncode == 0:
                arch_flags += ["-arch", arch]

    print(f"Discovered {compiler} arch flags: {arch_flags}")
    return arch_flags


def extra_compile_args():
    """Returns extra compiler args for platform."""
    if sys.platform == "win32":
        return ["/std:c++14"]  # for Visual Studio C++

    return ["-std=c++14"]


def get_extra_link_args():
    """Get extra link args for Windows to link against Python library."""
    if sys.platform != "win32":
        return []
    # On Windows, we need to explicitly link against pythonXX.lib
    # Pass the full path to ensure the linker finds it
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    python_lib = path.join(sys.prefix, 'libs', f'python{version}.lib')
    print(f"DEBUG: Looking for Python lib at: {python_lib}")
    print(f"DEBUG: Exists: {path.exists(python_lib)}")
    if path.exists(python_lib):
        # Use /DEFAULTLIB to force linking
        return [f'/DEFAULTLIB:{python_lib}']
    # Fallback
    return [f'/DEFAULTLIB:python{version}.lib']


def make_command():
    """Returns the make command for the current platform."""
    return "make"


def cmake_available():
    """Check if CMake is available on the system."""
    import shutil
    return shutil.which('cmake') is not None


def dll_suffix():
    """Returns the file suffix ("extension") of a DLL"""
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()


def build_gui_bundle():
    """Build the scalene-gui TypeScript bundle.

    Tries multiple approaches in order:
    1. If bundle already exists, skip
    2. Try using esbuild directly (fastest, no npm needed if esbuild installed globally)
    3. Fall back to npm if esbuild not found
    """
    import shutil
    import subprocess

    gui_dir = path.join(path.dirname(__file__), "scalene", "scalene-gui")
    bundle_file = path.join(gui_dir, "scalene-gui-bundle.js")

    # Skip if bundle already exists
    if path.exists(bundle_file):
        print(f"GUI bundle already exists: {bundle_file}")
        return True

    # Check if node_modules exists (dependencies installed)
    node_modules = path.join(gui_dir, "node_modules")
    if not path.exists(node_modules):
        # Need to install dependencies first
        npm_cmd = shutil.which("npm")
        if npm_cmd:
            print("Installing GUI dependencies...")
            try:
                subprocess.run([npm_cmd, "install"], cwd=gui_dir, check=True)
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to install dependencies: {e}")
                return False
        else:
            print("Warning: npm not found and node_modules missing.")
            print("Please run 'npm install' in scalene/scalene-gui/")
            return False

    # Try esbuild directly first (works if installed globally or in node_modules)
    esbuild_cmd = shutil.which("esbuild")
    if not esbuild_cmd:
        # Check node_modules/.bin
        esbuild_local = path.join(gui_dir, "node_modules", ".bin", "esbuild")
        if path.exists(esbuild_local):
            esbuild_cmd = esbuild_local

    if esbuild_cmd:
        print("Building scalene-gui TypeScript bundle with esbuild...")
        try:
            subprocess.run([
                esbuild_cmd,
                "scalene-gui.ts",
                "--bundle",
                "--minify",
                "--sourcemap",
                "--target=es2020",
                "--outfile=scalene-gui-bundle.js",
                "--define:process.env.LANG=\"en_US.UTF-8\""
            ], cwd=gui_dir, check=True)
            print("GUI bundle built successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Warning: esbuild failed: {e}")

    # Fall back to npm run build
    npm_cmd = shutil.which("npm")
    if npm_cmd:
        print("Building scalene-gui TypeScript bundle with npm...")
        try:
            subprocess.run([npm_cmd, "run", "build"], cwd=gui_dir, check=True)
            print("GUI bundle built successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Warning: npm build failed: {e}")

    print("Warning: Could not build GUI bundle.")
    print("Please install Node.js and run 'npm install && npm run build' in scalene/scalene-gui/")
    return False


import setuptools.command.egg_info


def fetch_vendor_deps_windows():
    """Fetch vendor dependencies on Windows using git."""
    import shutil
    import subprocess

    vendor_dir = path.join(path.dirname(__file__), "vendor")
    heap_layers_dir = path.join(vendor_dir, "Heap-Layers")
    printf_dir = path.join(vendor_dir, "printf")

    # Create vendor directory if it doesn't exist
    if not path.exists(vendor_dir):
        print(f"Creating vendor directory: {vendor_dir}")
        Path(vendor_dir).mkdir(parents=True, exist_ok=True)

    # Fetch Heap-Layers if not present
    if not path.exists(path.join(heap_layers_dir, "heaplayers.h")):
        print("Fetching Heap-Layers...")
        if path.exists(heap_layers_dir):
            shutil.rmtree(heap_layers_dir)
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/emeryberger/Heap-Layers.git", heap_layers_dir],
            check=True
        )

    # Fetch printf if not present
    if not path.exists(path.join(printf_dir, "printf.cpp")):
        print("Fetching printf library...")
        if path.exists(printf_dir):
            shutil.rmtree(printf_dir)
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/mpaland/printf.git", printf_dir],
            check=True
        )
        # Create printf.cpp from printf.c
        printf_c = path.join(printf_dir, "printf.c")
        printf_cpp = path.join(printf_dir, "printf.cpp")
        if path.exists(printf_c):
            shutil.copy(printf_c, printf_cpp)
        # Patch printf.h
        printf_h = path.join(printf_dir, "printf.h")
        if path.exists(printf_h):
            with open(printf_h, encoding="utf-8") as f:
                content = f.read()
            content = content.replace("#define printf printf_", "//#define printf printf_")
            content = content.replace("#define vsnprintf vsnprintf_", "//#define vsnprintf vsnprintf_")
            with open(printf_h, "w", encoding="utf-8") as f:
                f.write(content)


class EggInfoCommand(setuptools.command.egg_info.egg_info):
    """Custom command to download vendor libs and build GUI before creating the egg_info."""

    def run(self):
        if sys.platform == "win32":
            fetch_vendor_deps_windows()
        else:
            self.spawn([make_command(), "vendor-deps"])
        # Build the TypeScript GUI bundle if needed
        build_gui_bundle()
        super().run()


# Force building platform-specific wheel to avoid the Windows wheel
# (which doesn't include libscalene, and thus would be considered "pure")
# being used for other platforms.
try:
    from wheel.bdist_wheel import bdist_wheel

    class BdistWheelCommand(bdist_wheel):
        def finalize_options(self):
            super().finalize_options()
            self.root_is_pure = False

except (ImportError, ModuleNotFoundError):
    # Disable wheel if `wheel` not installed.
    print(
        "If this installation does not work, run `pip install setuptools wheel` and try again."
    )
    BdistWheelCommand = None

import setuptools.command.build_ext


class BuildExtCommand(setuptools.command.build_ext.build_ext):
    """Custom command that runs 'make' to generate libscalene, and also does MacOS
    supported --arch flag discovery."""

    def build_extensions(self):
        # Ensure vendor dependencies are available before building extensions
        if sys.platform == "win32":
            fetch_vendor_deps_windows()
            self._fix_windows_arch_mismatch()
        else:
            self.spawn([make_command(), "vendor-deps"])

        arch_flags = []
        if sys.platform == "darwin":
            # The only sure way to tell which compiler build_ext is going to use
            # seems to be to customize a build_ext and look at its internal flags :(
            # Also, note that self.plat_name here isn't "...-universal2" even if that
            # is what we're building; that's only in bdist_wheel.plat_name.
            arch_flags += compiler_archs(self.compiler.compiler_cxx[0])
            for ext in self.extensions:
                # While the flags _could_ be different between the programs used for
                # C and C++ compilation and linking, we have no way to adapt them here,
                # so it seems best to just use them and let it error out if not recognized.
                ext.extra_compile_args += arch_flags
                ext.extra_link_args += arch_flags

        super().build_extensions()

        # Build libscalene for the current platform
        if sys.platform == "win32":
            self.build_libscalene_windows()
        else:
            self.build_libscalene(arch_flags)

    def _fix_windows_arch_mismatch(self):
        """Fix MSVC toolchain arch mismatch on ARM64 Windows with x64 Python.

        On ARM64 Windows, MSVC may auto-select the ARM64 cross-compiler,
        but if the Python interpreter is x64 (running under emulation),
        the ARM64 object files won't link against the x64 python3XX.lib.
        Force the toolchain to match the Python interpreter's architecture.
        """
        import platform

        machine = platform.machine().lower()
        # Determine Python's target arch from the platform tag
        plat = sysconfig.get_platform()  # e.g. 'win-amd64' or 'win-arm64'
        if "arm64" in plat:
            target_arch = "arm64"
        elif "amd64" in plat or "x86_64" in plat:
            target_arch = "x64"
        else:
            target_arch = "x86"

        is_arm64_host = machine in ("arm64", "aarch64")
        if is_arm64_host and target_arch == "x64":
            # ARM64 Windows but x64 Python — force x64 toolchain
            print(f"Detected ARM64 host with x64 Python (platform={sysconfig.get_platform()})")
            print("Setting VSCMD_ARG_TGT_ARCH=x64 to select correct MSVC toolchain")
            environ["VSCMD_ARG_TGT_ARCH"] = "x64"
            # Also reinitialize the compiler to pick up the correct toolchain
            try:
                from setuptools._distutils._msvccompiler import MSVCCompiler
            except ImportError:
                from distutils._msvccompiler import MSVCCompiler
            self.compiler = MSVCCompiler()
            self.compiler.initialize()

    def build_libscalene(self, arch_flags):
        scalene_temp = path.join(self.build_temp, "scalene")
        scalene_lib = path.join(self.build_lib, "scalene")
        libscalene = "libscalene" + dll_suffix()
        self.mkpath(scalene_temp)
        self.mkpath(scalene_lib)
        self.spawn(
            [make_command(), "OUTDIR=" + scalene_temp, "ARCH=" + " ".join(arch_flags)]
        )
        self.copy_file(
            path.join(scalene_temp, libscalene), path.join(scalene_lib, libscalene)
        )

    def build_libscalene_windows(self):
        """Build libscalene on Windows using CMake."""
        scalene_temp = path.join(self.build_temp, "scalene")
        scalene_lib = path.join(self.build_lib, "scalene")
        libscalene = "libscalene" + dll_suffix()
        cmake_build_dir = path.join(self.build_temp, "cmake_build")

        self.mkpath(scalene_temp)
        self.mkpath(scalene_lib)
        self.mkpath(cmake_build_dir)

        if not cmake_available():
            print("Warning: CMake not found. Memory profiling will not be available on Windows.")
            return

        try:
            # Detect architecture for Windows builds
            import platform
            machine = platform.machine().lower()
            if machine in ('amd64', 'x86_64'):
                cmake_arch = 'x64'
            elif machine in ('arm64', 'aarch64'):
                cmake_arch = 'ARM64'
            else:
                cmake_arch = None
                print(f"Warning: Unknown architecture '{machine}', using default CMake generator")

            # Configure with CMake
            cmake_config = [
                'cmake',
                '-S', '.',
                '-B', cmake_build_dir,
                '-DCMAKE_BUILD_TYPE=Release',
                f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={scalene_temp}',
                f'-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={scalene_temp}',
            ]

            # Add architecture-specific options for Visual Studio generator
            if cmake_arch:
                cmake_config.extend(['-A', cmake_arch])
                print(f"Building libscalene.dll for {cmake_arch} architecture")

            self.spawn(cmake_config)

            # Build
            self.spawn([
                'cmake',
                '--build', cmake_build_dir,
                '--config', 'Release',
            ])

            # Copy the DLL
            # On Windows, CMake may put the DLL in various locations depending on
            # how the build is configured. Check all possible locations.
            project_dir = path.dirname(path.abspath(__file__))
            possible_paths = [
                path.join(scalene_temp, libscalene),
                path.join(scalene_temp, 'Release', libscalene),
                path.join(cmake_build_dir, 'Release', libscalene),
                path.join(cmake_build_dir, libscalene),
                # CMakeLists.txt may override output dir to project's scalene folder
                path.join(project_dir, 'scalene', libscalene),
                path.join(project_dir, 'scalene', 'Release', libscalene),
            ]

            for src_path in possible_paths:
                if path.exists(src_path):
                    print(f"Found {libscalene} at {src_path}")
                    self.copy_file(src_path, path.join(scalene_lib, libscalene))
                    print(f"Copied to {path.join(scalene_lib, libscalene)}")
                    break
            else:
                print(f"Warning: Could not find {libscalene} after build")
                print(f"Searched in: {possible_paths}")

        except Exception as e:
            print(f"Warning: Failed to build libscalene on Windows: {e}")
            print("Memory profiling will not be available on this platform.")

    def copy_extensions_to_source(self):
        # self.inplace is temporarily overridden while running build_extensions,
        # so inplace copying (for pip install -e, setup.py develop) must be done here.

        super().copy_extensions_to_source()

        # Copy libscalene for all platforms (including Windows)
        scalene_lib = path.join(self.build_lib, "scalene")
        inplace_dir = self.get_finalized_command("build_py").get_package_dir(
            "scalene"
        )
        libscalene = "libscalene" + dll_suffix()
        libscalene_path = path.join(scalene_lib, libscalene)
        if path.exists(libscalene_path):
            self.copy_file(libscalene_path, path.join(inplace_dir, libscalene))


get_line_atomic = Extension(
    "scalene.get_line_atomic",
    include_dirs=[".", "vendor/Heap-Layers", "vendor/Heap-Layers/utility"],
    sources=["src/source/get_line_atomic.cpp"],
    extra_compile_args=extra_compile_args(),
    extra_link_args=get_extra_link_args(),
    py_limited_api=sys.platform != "win32",  # Limited API has issues on Windows
    language="c++",
)

pywhere = Extension(
    "scalene.pywhere",
    include_dirs=[".", "src", "src/include"],
    depends=["src/include/traceconfig.hpp"],
    sources=["src/source/pywhere.cpp", "src/source/traceconfig.cpp"],
    extra_compile_args=extra_compile_args(),
    extra_link_args=get_extra_link_args(),
    py_limited_api=False,
    language="c++",
)

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
dev_build = (".dev" + environ["DEV_BUILD"]) if "DEV_BUILD" in environ else ""


def bdist_wheel_options():
    if sys.platform == "darwin":
        # Build universal wheels on MacOS.
        # ---
        # On MacOS >= 11, all builds are compatible within a major MacOS version, so Python "floors"
        # all minor versions to 0, leading to tags like like "macosx_11_0_universal2". If you use
        # the actual (non-0) minor name in the build platform, it isn't recognized.
        # ---
        # It would be nice to check whether we're actually building multi-architecture,
        # but that depends on the platforms supported by the compiler build_ext wants to use,
        # which is hard to obtain (see BuildExtCommand above).
        import platform

        v = platform.mac_ver()[0]
        major = int(v.split(".")[0])
        if major >= 11:
            v = f"{major}.0"
        return {"plat_name": f"macosx-{v}-universal2"}

    return {}


setup(
    version=scalene_version + dev_build,
    packages=find_packages(),
    cmdclass={
        "bdist_wheel": BdistWheelCommand,
        "egg_info": EggInfoCommand,
        "build_ext": BuildExtCommand,
    },
    ext_modules=[get_line_atomic, pywhere],  # Now supported on all platforms
    include_package_data=True,
    options={"bdist_wheel": bdist_wheel_options()},
)
