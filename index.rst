.. figure::
   https://github.com/plasma-umass/scalene/raw/master/docs/scalene-icon-white.png
   :alt: scalene

   scalene

Scalene: a Python CPU+GPU+memory profiler with AI-powered optimization proposals
================================================================================

by `Emery Berger <https://emeryberger.com>`__, `Sam
Stern <https://samstern.me/>`__, and `Juan Altmayer
Pizzorno <https://github.com/jaltmayerpizzorno>`__.

|Scalene community Slack|\ `Scalene community
Slack <https://join.slack.com/t/scaleneprofil-jge3234/shared_invite/zt-110vzrdck-xJh5d4gHnp5vKXIjYD3Uwg>`__

|PyPI Latest Release|\ |Anaconda-Server Badge| |Downloads|\ |Anaconda
downloads| |image1| |Python versions|\ |Visual Studio Code Extension
version| |License|

.. figure::
   https://github.com/plasma-umass/scalene/raw/master/docs/Ozsvald-tweet.png
   :alt: Ozsvald tweet

   Ozsvald tweet

(tweet from Ian Ozsvald, author of `High Performance
Python <https://smile.amazon.com/High-Performance-Python-Performant-Programming/dp/1492055026/ref=sr_1_1?crid=texbooks>`__)

.. figure::
   https://github.com/plasma-umass/scalene/raw/master/docs/semantic-scholar-success.png
   :alt: Semantic Scholar success story

   Semantic Scholar success story

**Scalene web-based user interface:**
http://plasma-umass.org/scalene-gui/

About Scalene
-------------

Scalene is a high-performance CPU, GPU *and* memory profiler for Python
that does a number of things that other Python profilers do not and
cannot do. It runs orders of magnitude faster than many other profilers
while delivering far more detailed information. It is also the first
profiler ever to incorporate AI-powered proposed optimizations.

AI-powered optimization suggestions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

   **Note**

   To enable AI-powered optimization suggestions, you need to enter an
   `OpenAI key <https://openai.com/api/>`__ in the box under “Advanced
   options”. *Your account will need to have a positive balance for this
   to work* (check your balance at
   https://platform.openai.com/account/usage).

Once you’ve entered your OpenAI key (see above), click on the lightning
bolt (⚡) beside any line or the explosion (💥) for an entire region of
code to generate a proposed optimization. Click on a proposed
optimization to copy it to the clipboard.

You can click as many times as you like on the lightning bolt or
explosion, and it will generate different suggested optimizations. Your
mileage may vary, but in some cases, the suggestions are quite
impressive (e.g., order-of-magnitude improvements).

Quick Start
~~~~~~~~~~~

Installing Scalene:
^^^^^^^^^^^^^^^^^^^

.. code:: console

   python3 -m pip install -U scalene

or

.. code:: console

   conda install -c conda-forge scalene

Using Scalene:
^^^^^^^^^^^^^^

After installing Scalene, you can use Scalene at the command line, or as
a Visual Studio Code extension.

.. raw:: html

   <details>

.. raw:: html

   <summary>

Using the Scalene VS Code Extension:

.. raw:: html

   </summary>

First, install the Scalene extension from the VS Code Marketplace or by
searching for it within VS Code by typing Command-Shift-X (Mac) or
Ctrl-Shift-X (Windows). Once that’s installed, click Command-Shift-P or
Ctrl-Shift-P to open the Command Palette. Then select “Scalene:
AI-powered profiling…” (you can start typing Scalene and it will pop up
if it’s installed). Run that and, assuming your code runs for at least a
second, a Scalene profile will appear in a webview.

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Commonly used command-line options:

.. raw:: html

   </summary>

Scalene uses a verb-based command structure with two main commands: ``run`` (to profile) and ``view`` (to display results).

.. code:: console

   # Profile a program (saves to scalene-profile.json)
   scalene run your_prog.py
   python3 -m scalene run your_prog.py              # equivalent alternative

   # View a profile
   scalene view                                     # open profile in browser
   scalene view --cli                               # view in terminal
   scalene view --html                              # save to scalene-profile.html

   # Common profiling options
   scalene run --cpu-only your_prog.py              # only profile CPU (faster)
   scalene run -o results.json your_prog.py         # custom output filename
   scalene run -c config.yaml your_prog.py          # load options from config file

   # Pass arguments to your program (use --- separator)
   scalene run your_prog.py --- --arg1 --arg2

   # Get help
   scalene --help                                   # main help
   scalene run --help                               # profiling options
   scalene run --help-advanced                      # advanced profiling options
   scalene view --help                              # viewing options

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Using Scalene programmatically in your code:

.. raw:: html

   </summary>

Invoke using ``scalene`` as above and then:

.. code:: python

   from scalene import scalene_profiler

   # Turn profiling on
   scalene_profiler.start()

   # your code

   # Turn profiling off
   scalene_profiler.stop()

.. code:: python

   from scalene.scalene_profiler import enable_profiling

   with enable_profiling():
       # do something

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Using Scalene to profile only specific functions via @profile:

.. raw:: html

   </summary>

Just preface any functions you want to profile with the ``@profile``
decorator and run it with Scalene:

.. code:: python

   # do not import profile!

   @profile
   def slow_function():
       import time
       time.sleep(3)

.. raw:: html

   </details>

Web-based GUI
^^^^^^^^^^^^^

Scalene has both a CLI and a web-based GUI `(demo
here) <https://scalene-gui.github.io/scalene-gui/>`__.

By default, once Scalene has profiled your program, it will open a tab
in a web browser with an interactive user interface (all processing is
done locally). Hover over bars to see breakdowns of CPU and memory
consumption, and click on underlined column headers to sort the columns.
The generated file ``profile.html`` is self-contained and can be saved
for later use.

|Scalene web GUI|

Scalene Overview
----------------

Scalene talk (PyCon US 2021)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`This talk <https://youtu.be/5iEf-_7mM1k>`__ presented at PyCon 2021
walks through Scalene’s advantages and how to use it to debug the
performance of an application (and provides some technical details on
its internals). We highly recommend watching this video!

|Scalene presentation at PyCon 2021|

Fast and Accurate
~~~~~~~~~~~~~~~~~

-  Scalene is **fast**. It uses sampling instead of instrumentation or
   relying on Python’s tracing facilities. Its overhead is typically no
   more than 10-20% (and often less).

-  Scalene is **accurate**. We tested CPU profiler accuracy and found
   that Scalene is among the most accurate profilers, correctly
   measuring time taken.

.. figure::
   https://github.com/plasma-umass/scalene/raw/master/docs/cpu-accuracy-comparison.png
   :alt: Profiler accuracy

   Profiler accuracy

-  Scalene performs profiling **at the line level** *and* **per
   function**, pointing to the functions and the specific lines of code
   responsible for the execution time in your program.

CPU profiling
~~~~~~~~~~~~~

-  Scalene **separates out time spent in Python from time in native
   code** (including libraries). Most Python programmers aren’t going to
   optimize the performance of native code (which is usually either in
   the Python implementation or external libraries), so this helps
   developers focus their optimization efforts on the code they can
   actually improve.
-  Scalene **highlights hotspots** (code accounting for significant
   percentages of CPU time or memory allocation) in red, making them
   even easier to spot.
-  Scalene also separates out **system time**, making it easy to find
   I/O bottlenecks.

GPU profiling
~~~~~~~~~~~~~

-  Scalene reports **GPU time** (currently limited to NVIDIA-based
   systems).

Memory profiling
~~~~~~~~~~~~~~~~

-  Scalene **profiles memory usage**. In addition to tracking CPU usage,
   Scalene also points to the specific lines of code responsible for
   memory growth. It accomplishes this via an included specialized
   memory allocator.
-  Scalene separates out the percentage of **memory consumed by Python
   code vs. native code**.
-  Scalene produces **per-line memory profiles**.
-  Scalene **identifies lines with likely memory leaks**.
-  Scalene **profiles copying volume**, making it easy to spot
   inadvertent copying, especially due to crossing Python/library
   boundaries (e.g., accidentally converting ``numpy`` arrays into
   Python arrays, and vice versa).

Other features
~~~~~~~~~~~~~~

-  Scalene can produce **reduced profiles** (via ``--reduced-profile``)
   that only report lines that consume more than 1% of CPU or perform at
   least 100 allocations.
-  Scalene supports ``@profile`` decorators to profile only specific
   functions.
-  When Scalene is profiling a program launched in the background (via
   ``&``), you can **suspend and resume profiling**.

Comparison to Other Profilers
=============================

Performance and Features
------------------------

Below is a table comparing the **performance and features** of various
profilers to Scalene.

.. figure::
   https://raw.githubusercontent.com/plasma-umass/scalene/master/docs/images/profiler-comparison.png
   :alt: Performance and feature comparison

   Performance and feature comparison

-  **Slowdown**: the slowdown when running a benchmark from the
   Pyperformance suite. Green means less than 2x overhead. Scalene’s
   overhead is just a 35% slowdown.

Scalene has all of the following features, many of which only Scalene
supports:

-  **Lines or functions**: does the profiler report information only for
   entire functions, or for every line – Scalene does both.
-  **Unmodified Code**: works on unmodified code.
-  **Threads**: supports Python threads.
-  **Multiprocessing**: supports use of the ``multiprocessing`` library
   – *Scalene only*
-  **Python vs. C time**: breaks out time spent in Python vs. native
   code (e.g., libraries) – *Scalene only*
-  **System time**: breaks out system time (e.g., sleeping or performing
   I/O) – *Scalene only*
-  **Profiles memory**: reports memory consumption per line / function
-  **GPU**: reports time spent on an NVIDIA GPU (if present) – *Scalene
   only*
-  **Memory trends**: reports memory use over time per line / function –
   *Scalene only*
-  **Copy volume**: reports megabytes being copied per second – *Scalene
   only*
-  **Detects leaks**: automatically pinpoints lines responsible for
   likely memory leaks – *Scalene only*

Output
------

If you include the ``--cli`` option, Scalene prints annotated source
code for the program being profiled (as text, JSON (``--json``), or HTML
(``--html``)) and any modules it uses in the same directory or
subdirectories (you can optionally have it ``--profile-all`` and only
include files with at least a ``--cpu-percent-threshold`` of time). Here
is a snippet from ``pystone.py``.

.. figure::
   https://raw.githubusercontent.com/plasma-umass/scalene/master/docs/images/sample-profile-pystone.png
   :alt: Example profile

   Example profile

-  **Memory usage at the top**: Visualized by “sparklines”, memory
   consumption over the runtime of the profiled code.
-  **“Time Python”**: How much time was spent in Python code.
-  **“native”**: How much time was spent in non-Python code (e.g.,
   libraries written in C/C++).
-  **“system”**: How much time was spent in the system (e.g., I/O).
-  **“GPU”**: (not shown here) How much time spent on the GPU, if your
   system has an NVIDIA GPU installed.
-  **“Memory Python”**: How much of the memory allocation happened on
   the Python side of the code, as opposed to in non-Python code (e.g.,
   libraries written in C/C++).
-  **“net”**: Positive net memory numbers indicate total memory
   allocation in megabytes; negative net memory numbers indicate memory
   reclamation.
-  **“timeline / %”**: Visualized by “sparklines”, memory consumption
   generated by this line over the program runtime, and the percentages
   of total memory activity this line represents.
-  **“Copy (MB/s)”**: The amount of megabytes being copied per second
   (see “About Scalene”).

Scalene
-------

The following command runs Scalene on a provided example program.

.. code:: console

   scalene test/testme.py

.. raw:: html

   <details>

.. raw:: html

   <summary>

Click to see all Scalene’s options (available by running with –help)

.. raw:: html

   </summary>

.. code:: console

   % scalene --help
   Scalene: a high-precision CPU and memory profiler
   https://github.com/plasma-umass/scalene

   commands:
     run     Profile a Python program (saves to scalene-profile.json)
     view    View an existing profile in browser or terminal

   examples:
     % scalene run your_program.py              # profile, save to scalene-profile.json
     % scalene view                             # view scalene-profile.json in browser
     % scalene view --cli                       # view profile in terminal

   in Jupyter, line mode:
     %scrun [options] statement

   in Jupyter, cell mode:
     %%scalene [options]
      your code here

   % scalene run --help
   Profile a Python program with Scalene.

   examples:
     % scalene run prog.py                 # profile, save to scalene-profile.json
     % scalene run -o my.json prog.py      # save to custom file
     % scalene run --cpu-only prog.py      # profile CPU only (faster)
     % scalene run -c scalene.yaml prog.py # load options from config file
     % scalene run prog.py --- --arg       # pass args to program
     % scalene run --help-advanced         # show advanced options

   options:
     -h, --help            show this help message and exit
     -o, --outfile OUTFILE output file (default: scalene-profile.json)
     --cpu-only            only profile CPU time (no memory/GPU)
     -c, --config FILE     load options from YAML config file
     --help-advanced       show advanced options

   % scalene run --help-advanced
   Advanced options for scalene run:

   background profiling:
     Use --off to start with profiling disabled, then control from another terminal:
       % scalene run --off prog.py          # start with profiling off
       % python3 -m scalene.profile --on  --pid <PID>   # resume profiling
       % python3 -m scalene.profile --off --pid <PID>   # suspend profiling

   options:
     --profile-all         profile all code, not just the target program
     --profile-only PATH   only profile files containing these strings (comma-separated)
     --profile-exclude PATH exclude files containing these strings (comma-separated)
     --profile-system-libraries  profile Python stdlib and installed packages (default: skip)
     --gpu                 profile GPU time and memory
     --memory              profile memory usage
     --stacks              collect stack traces
     --profile-interval N  output profiles every N seconds (default: inf)
     --use-virtual-time    measure only CPU time, not I/O or blocking
     --cpu-percent-threshold N  only report lines with at least N% CPU (default: 1%)
     --cpu-sampling-rate N CPU sampling rate in seconds (default: 0.01)
     --malloc-threshold N  only report lines with at least N allocations (default: 100)
     --memory-leak-detector  EXPERIMENTAL: report likely memory leaks
     --on                  start with profiling on (default)
     --off                 start with profiling off

   % scalene view --help
   View an existing Scalene profile.

   examples:
     % scalene view                    # open in browser
     % scalene view --cli              # view in terminal
     % scalene view --html             # save to scalene-profile.html
     % scalene view myprofile.json     # open specific profile in browser

   options:
     -h, --help     show this help message and exit
     --cli          display profile in the terminal
     --html         save to scalene-profile.html (no browser)
     -r, --reduced  only show lines with activity (--cli mode)

.. raw:: html

   </details>

Scalene with Jupyter
~~~~~~~~~~~~~~~~~~~~

.. raw:: html

   <details>

.. raw:: html

   <summary>

Instructions for installing and using Scalene with Jupyter notebooks

.. raw:: html

   </summary>

`This
notebook <https://nbviewer.jupyter.org/github/plasma-umass/scalene/blob/master/docs/scalene-demo.ipynb>`__
illustrates the use of Scalene in Jupyter.

Installation:

.. code:: console

   !pip install scalene
   %load_ext scalene

Line mode:

.. code:: console

   %scrun [options] statement

Cell mode:

.. code:: console

   %%scalene [options]
   code...
   code...

.. raw:: html

   </details>

Installation
------------

.. raw:: html

   <details open>

.. raw:: html

   <summary>

Using pip (Mac OS X, Linux, Windows, and WSL2)

.. raw:: html

   </summary>

Scalene is distributed as a ``pip`` package and works on Mac OS X, Linux
(including Ubuntu in `Windows
WSL2 <https://docs.microsoft.com/en-us/windows/wsl/wsl2-index>`__) and
(with limitations) Windows platforms.

   **Note**

   The Windows version currently only supports CPU and GPU profiling,
   but not memory or copy profiling.

You can install it as follows:

.. code:: console

     % pip install -U scalene

or

.. code:: console

     % python3 -m pip install -U scalene

You may need to install some packages first.

See https://stackoverflow.com/a/19344978/4954434 for full instructions
for all Linux flavors.

For Ubuntu/Debian:

.. code:: console

     % sudo apt install git python3-all-dev

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Using conda (Mac OS X, Linux, Windows, and WSL2)

.. raw:: html

   </summary>

.. code:: console

     % conda install -c conda-forge scalene

Scalene is distributed as a ``conda`` package and works on Mac OS X,
Linux (including Ubuntu in `Windows
WSL2 <https://docs.microsoft.com/en-us/windows/wsl/wsl2-index>`__) and
(with limitations) Windows platforms.

   **Note**

   The Windows version currently only supports CPU and GPU profiling,
   but not memory or copy profiling.

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

On ArchLinux

.. raw:: html

   </summary>

You can install Scalene on Arch Linux via the `AUR
package <https://aur.archlinux.org/packages/python-scalene-git/>`__. Use
your favorite AUR helper, or manually download the ``PKGBUILD`` and run
``makepkg -cirs`` to build. Note that this will place ``libscalene.so``
in ``/usr/lib``; modify the below usage instructions accordingly.

.. raw:: html

   </details>

Frequently Asked Questions
==========================

.. raw:: html

   <details>

.. raw:: html

   <summary>

Can I use Scalene with PyTest?

.. raw:: html

   </summary>

**A:** Yes! You can run it as follows (for example):

``scalene run -m pytest your_test.py``

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Is there any way to get shorter profiles or do more targeted profiling?

.. raw:: html

   </summary>

**A:** Yes! There are several options:

1. Use ``--reduced-profile`` to include only lines and files with
   memory/CPU/GPU activity.
2. Use ``--profile-only`` to include only filenames containing specific
   strings (as in, ``--profile-only foo,bar,baz``).
3. Decorate functions of interest with ``@profile`` to have Scalene
   report *only* those functions.
4. Turn profiling on and off programmatically by importing Scalene
   profiler (``from scalene import scalene_profiler``) and then turning
   profiling on and off via ``scalene_profiler.start()`` and
   ``scalene_profiler.stop()``. By default, Scalene runs with profiling
   on, so to delay profiling until desired, use the ``--off``
   command-line option (``scalene run --off yourprogram.py``).

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

How do I run Scalene in PyCharm?

.. raw:: html

   </summary>

**A:** In PyCharm, you can run Scalene at the command line by opening
the terminal at the bottom of the IDE and running a Scalene command
(e.g., ``scalene run <your program>``). Then use ``scalene view --html``
to generate an HTML file (``scalene-profile.html``) that you can view in the IDE.

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

How do I use Scalene with Django?

.. raw:: html

   </summary>

**A:** Pass in the ``--noreload`` option (see
https://github.com/plasma-umass/scalene/issues/178).

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

Does Scalene work with gevent/Greenlets?

.. raw:: html

   </summary>

**A:** Yes! Put the following code in the beginning of your program, or
modify the call to ``monkey.patch_all`` as below:

.. code:: python

   from gevent import monkey
   monkey.patch_all(thread=False)

.. raw:: html

   </details>

.. raw:: html

   <details>

.. raw:: html

   <summary>

How do I use Scalene with PyTorch on the Mac?

.. raw:: html

   </summary>

**A:** Scalene works with PyTorch version 1.5.1 on Mac OS X. There’s a
bug in newer versions of PyTorch
(https://github.com/pytorch/pytorch/issues/57185) that interferes with
Scalene (discussion here:
https://github.com/plasma-umass/scalene/issues/110), but only on Macs.

.. raw:: html

   </details>

Technical Information
=====================

For details about how Scalene works, please see the following paper,
which won the Jay Lepreau Best Paper Award at `OSDI
2023 <https://www.usenix.org/conference/osdi23/presentation/berger>`__:
`Triangulating Python Performance Issues with
Scalene <https://arxiv.org/pdf/2212.07597>`__. (Note that this paper
does not include information about the AI-driven proposed
optimizations.)

.. raw:: html

   <details>

.. raw:: html

   <summary>

To cite Scalene in an academic paper, please use the following:

.. raw:: html

   </summary>

.. code:: latex

   @inproceedings{288540,
   author = {Emery D. Berger and Sam Stern and Juan Altmayer Pizzorno},
   title = {Triangulating Python Performance Issues with {S}calene},
   booktitle = {{17th USENIX Symposium on Operating Systems Design and Implementation (OSDI 23)}},
   year = {2023},
   isbn = {978-1-939133-34-2},
   address = {Boston, MA},
   pages = {51--64},
   url = {https://www.usenix.org/conference/osdi23/presentation/berger},
   publisher = {USENIX Association},
   month = jul
   }

.. raw:: html

   </details>

Success Stories
===============

If you use Scalene to successfully debug a performance problem, please
`add a comment to this
issue <https://github.com/plasma-umass/scalene/issues/58>`__!

Acknowledgements
================

Logo created by `Sophia
Berger <https://www.linkedin.com/in/sophia-berger/>`__.

This material is based upon work supported by the National Science
Foundation under Grant No. 1955610. Any opinions, findings, and
conclusions or recommendations expressed in this material are those of
the author(s) and do not necessarily reflect the views of the National
Science Foundation.

.. |Scalene community Slack| image:: https://github.com/plasma-umass/scalene/raw/master/docs/images/slack-logo.png
   :target: https://join.slack.com/t/scaleneprofil-jge3234/shared_invite/zt-110vzrdck-xJh5d4gHnp5vKXIjYD3Uwg
.. |PyPI Latest Release| image:: https://img.shields.io/pypi/v/scalene.svg
   :target: https://pypi.org/project/scalene/
.. |Anaconda-Server Badge| image:: https://img.shields.io/conda/v/conda-forge/scalene
   :target: https://anaconda.org/conda-forge/scalene
.. |Downloads| image:: https://static.pepy.tech/badge/scalene
   :target: https://pepy.tech/project/scalene
.. |Anaconda downloads| image:: https://img.shields.io/conda/d/conda-forge/scalene?logo=conda
   :target: https://anaconda.org/conda-forge/scalene
.. |image1| image:: https://static.pepy.tech/badge/scalene/month
   :target: https://pepy.tech/project/scalene
.. |Python versions| image:: https://img.shields.io/pypi/pyversions/scalene.svg?style=flat-square
.. |Visual Studio Code Extension version| image:: https://img.shields.io/visual-studio-marketplace/v/emeryberger.scalene?logo=visualstudiocode
   :target: https://marketplace.visualstudio.com/items?itemName=EmeryBerger.scalene
.. |License| image:: https://img.shields.io/github/license/plasma-umass/scalene
.. |Scalene web GUI| image:: https://raw.githubusercontent.com/plasma-umass/scalene/master/docs/scalene-gui-example.png
   :target: https://raw.githubusercontent.com/plasma-umass/scalene/master/docs/scalene-gui-example-full.png
.. |Scalene presentation at PyCon 2021| image:: https://raw.githubusercontent.com/plasma-umass/scalene/master/docs/images/scalene-video-img.png
   :target: https://youtu.be/5iEf-_7mM1k
