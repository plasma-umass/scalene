from setuptools import setup, find_packages
from setuptools.extension import Extension
from scalene.scalene_version import scalene_version
from os import path, environ
import sys

def multiarch_args():
    """Returns args requesting multi-architecture support, if applicable."""
    # On MacOS we build "universal2" packages, for both x86_64 and arm64/M1
    if sys.platform == 'darwin':
        return ['-arch', 'x86_64', '-arch', 'arm64']
    return []

def extra_compile_args():
    """Returns extra compiler args for platform."""
    if sys.platform == 'win32':
        return ['/std:c++14'] # for Visual Studio C++

    return ['-std=c++14'] + multiarch_args()

def make_command():
    return 'nmake' if sys.platform == 'win32' else 'make'

def dll_suffix():
    """Returns the file suffix ("extension") of a DLL"""
    if (sys.platform == 'win32'): return '.dll'
    if (sys.platform == 'darwin'): return '.dylib'
    return '.so'

def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()

import setuptools.command.egg_info
class EggInfoCommand(setuptools.command.egg_info.egg_info):
    """Custom command to download vendor libs before creating the egg_info."""
    def run(self):
        self.spawn([make_command(), 'vendor-deps'])
        super().run()

import setuptools.command.build_ext
class BuildExtCommand(setuptools.command.build_ext.build_ext):
    """Custom command that runs 'make' to generate libscalene."""
    def run(self):
        super().run()
        self.build_libscalene()

    def build_libscalene(self):
        scalene_temp = path.join(self.build_temp, 'scalene')
        scalene_lib = path.join(self.build_lib, 'scalene')
        libscalene = 'libscalene' + dll_suffix()
        self.mkpath(scalene_temp)
        self.mkpath(scalene_lib)
        self.spawn([make_command(), 'OUTDIR=' + scalene_temp,
                    'ARCH=' + ' '.join(multiarch_args())])
        # No build of DLL for Windows currently.
        if (sys.platform == 'win32'):
            return
        self.copy_file(path.join(scalene_temp, libscalene),
                       path.join(scalene_lib, libscalene))
        if self.inplace:
            self.copy_file(path.join(scalene_lib, libscalene),
                           path.join('scalene', libscalene))

get_line_atomic = Extension('scalene.get_line_atomic',
    include_dirs=['.', 'vendor/Heap-Layers', 'vendor/Heap-Layers/utility'],
    sources=['src/source/get_line_atomic.cpp'],
    extra_compile_args=extra_compile_args(),
    extra_link_args=multiarch_args(),
    py_limited_api=True, # for binary compatibility
    language="c++"
)

# if TWINE_REPOSITORY=testpypi, we're testing packaging. Build using a ".devN"
# (monotonically increasing, not too big) suffix in the version number, so that
# we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
testing = 'TWINE_REPOSITORY' in environ and environ['TWINE_REPOSITORY'] == 'testpypi'
if testing:
    import subprocess
    import time
    version_timestamp = int(subprocess.check_output(["git", "log", "-1", "--format=%ct",
                                                     "scalene/scalene_version.py"]))
    mins_since_version = (time.time() - version_timestamp)/60

setup(
    name="scalene",
    version=scalene_version + (f'.dev{int(mins_since_version/5)}' if testing else ''),
    description="Scalene: A high-resolution, low-overhead CPU, GPU, and memory profiler for Python",
    keywords="performance memory profiler",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/emeryberger/scalene",
    author="Emery Berger",
    author_email="emery@cs.umass.edu",
    license="Apache License 2.0",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: IPython",
        "Framework :: Jupyter",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Software Development",
        "Topic :: Software Development :: Debuggers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows :: Windows 10"
    ],
    packages=find_packages(),
    cmdclass={
        'egg_info': EggInfoCommand,
        'build_ext': BuildExtCommand,
    },
    install_requires=[
        "rich>=9.2.10",
        "cloudpickle>=1.5.0",
        "nvidia-ml-py==11.450.51",
        "numpy"
    ],
    ext_modules=[get_line_atomic],
    setup_requires=['setuptools_scm'],
    include_package_data=True,
    entry_points={"console_scripts": ["scalene = scalene.__main__:main"]},
    python_requires=">=3.7",
)
