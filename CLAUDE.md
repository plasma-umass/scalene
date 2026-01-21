# Scalene Development Guide

## Project Overview

Scalene is a high-performance CPU, GPU, and memory profiler for Python with AI-powered optimization proposals. It runs significantly faster than other Python profilers while providing detailed performance information. See the paper `docs/osdi23-berger.pdf` for technical details on Scalene's design.

**Key features:**
- CPU, GPU (NVIDIA/Apple), and memory profiling
- AI-powered optimization suggestions (OpenAI, Anthropic, Azure, Amazon Bedrock, Gemini, Ollama)
- Web-based GUI and CLI interfaces
- Jupyter notebook support via magic commands (`%scrun`, `%%scalene`)
- Line-by-line profiling with low overhead
- Separates Python time from native/C time

**Platform support:** Linux, macOS, WSL 2 (full support); Windows (partial support)

## Build & Test Commands

```bash
# Install in development mode
pip install -e .

# Run all tests
python3 -m pytest tests/

# Run tests for a specific Python version
python3.X -m pytest tests/

# Run linters
mypy scalene
ruff check scalene

# Run a single test file
python3 -m pytest tests/test_coverup_83.py -v
```

## Project Structure

### Core Profiler Components (`scalene/`)

- **`scalene_profiler.py`** - Main profiler class (`Scalene`). Entry point for profiling. Uses signal-based sampling for CPU profiling. Coordinates all profiling subsystems.
- **`scalene_statistics.py`** - `ScaleneStatistics` class. Collects and aggregates profiling data. Key types: `ProfilingSample`, `MemcpyProfilingSample`. Uses `RunningStats` for statistical aggregation.
- **`scalene_output.py`** - Profile output formatting for CLI/HTML
- **`scalene_json.py`** - `ScaleneJSON` class for JSON output format
- **`scalene_analysis.py`** - Profile analysis logic

### Entry Points

- **`__main__.py`** - Entry point for `python -m scalene`
- **`profile.py`** - Entry point for `--on`/`--off` control of background profiling

### Configuration & Arguments

- **`scalene_config.py`** - Version info (`scalene_version`, `scalene_date`) and constants:
  - `SCALENE_PORT = 11235` - Default port for web UI
  - `NEWLINE_TRIGGER_LENGTH` - Must match `src/include/sampleheap.hpp`
- **`scalene_arguments.py`** - `ScaleneArguments` class (extends `argparse.Namespace`) with all profiler options and their defaults defined in `ScaleneArgumentsDict`
- **`scalene_parseargs.py`** - `ScaleneParseArgs.parse_args()` builds the argument parser. `RichArgParser` provides colored help output (uses Rich on Python < 3.14, native argparse colors on 3.14+)

### Signal Handling

- **`scalene_signals.py`** - Signal definitions for CPU sampling
- **`scalene_signal_manager.py`** - Manages signal handlers
- **`scalene_sigqueue.py`** - Signal queue management
- **`scalene_client_timer.py`** - Timer for periodic profiling

### GPU Support

- **`scalene_nvidia_gpu.py`** - NVIDIA GPU profiling via `pynvml`
- **`scalene_apple_gpu.py`** - Apple GPU profiling (Metal)
- **`scalene_accelerator.py`** - Generic accelerator interface
- **`scalene_neuron.py`** - AWS Neuron support

### Memory Profiling

- **`scalene_memory_profiler.py`** - Memory profiling logic
- **`scalene_leak_analysis.py`** - Memory leak detection (experimental, `--memory-leak-detector`)
- **`scalene_mapfile.py`** - `ScaleneMapFile` for memory-mapped communication with native extension
- **`scalene_preload.py`** - Sets up `LD_PRELOAD`/`DYLD_INSERT_LIBRARIES` for native memory tracking

### Jupyter Integration

- **`scalene_magics.py`** - Jupyter magic commands (`%scrun` for line mode, `%%scalene` for cell mode)
- **`scalene_jupyter.py`** - Jupyter notebook support utilities

### Replacement Modules (`replacement_*.py`)

These modules monkey-patch standard library functions to capture profiling data during blocking operations:
- **`replacement_fork.py`** - Tracks `os.fork()`
- **`replacement_exit.py`** - Tracks `sys.exit()`
- **`replacement_lock.py`**, **`replacement_mp_lock.py`**, **`replacement_sem_lock.py`** - Lock acquisition timing
- **`replacement_thread_join.py`**, **`replacement_pjoin.py`** - Thread/process join timing
- **`replacement_signal_fns.py`** - Signal function replacements
- **`replacement_poll_selector.py`** - I/O polling timing
- **`replacement_get_context.py`** - Multiprocessing context

### Utilities

- **`runningstats.py`** - `RunningStats` class for online statistical calculations (mean, variance)
- **`scalene_funcutils.py`** - Function utilities
- **`scalene_utility.py`** - General utilities
- **`sparkline.py`** - Sparkline generation for memory visualization
- **`syntaxline.py`** - Syntax-highlighted source code lines
- **`adaptive.py`** - Adaptive sampling logic
- **`time_info.py`** - Time measurement utilities
- **`sorted_reservoir.py`** - Reservoir sampling for bounded-size sample collection

### GUI (`scalene/scalene-gui/`)

Web-based GUI built with TypeScript, bundled with esbuild.

**Core Files:**
- **`index.html.template`** - Jinja2 template for main GUI page (rendered by `scalene_utility.py`)
- **`scalene-gui.ts`** - Main TypeScript entry point, UI event handlers, initialization
- **`scalene-gui-bundle.js`** - Bundled JavaScript output (generated, do not edit directly)

**AI Provider Modules:**
- **`openai.ts`** - OpenAI API integration (`sendPromptToOpenAI`, `fetchOpenAIModels`)
- **`anthropic.ts`** - Anthropic Claude API integration
- **`gemini.ts`** - Google Gemini API integration (`sendPromptToGemini`, `fetchGeminiModels`)
- **`optimizations.ts`** - Provider dispatch logic, prompt generation
- **`persistence.ts`** - localStorage persistence with environment variable fallbacks

**Support Files:**
- **`launchbrowser.py`** - Opens browser to GUI (default port 11235)
- **`find_browser.py`** - Cross-platform browser detection

**Vendored Assets (for offline support):**
- **`jquery-3.6.0.slim.min.js`** - jQuery (vendored locally, not loaded from CDN)
- **`bootstrap.min.css`** - Bootstrap 5.1.3 CSS
- **`bootstrap.bundle.min.js`** - Bootstrap 5.1.3 JS with Popper
- **`prism.css`** - Syntax highlighting styles
- **`favicon.ico`** - Scalene favicon
- **`scalene-image.png`** - Scalene logo

These assets are copied to a temp directory when serving via HTTP, enabling the GUI to work in air-gapped/offline environments.

**Building the GUI:**
```bash
cd scalene/scalene-gui
npx esbuild scalene-gui.ts --bundle --outfile=scalene-gui-bundle.js --format=iife --global-name=ScaleneGUI
```

### Native Extensions (`src/`)

C++ code for low-overhead memory allocation tracking:

**Headers (`src/include/`):**
- **`sampleheap.hpp`** - Sampling heap allocator. Key constant `NEWLINE` must match Python config.
- **`memcpysampler.hpp`** - Intercepts `memcpy` to track copy volume
- **`pywhere.hpp`** - Tracks Python file/line info for allocations
- **`samplefile.hpp`** - File-based communication with Python
- **`sampler.hpp`**, **`poissonsampler.hpp`**, **`thresholdsampler.hpp`** - Sampling strategies
- **`scaleneheader.hpp`** - Common header definitions

**Sources (`src/source/`):**
- **`libscalene.cpp`** - Main native library (loaded via `LD_PRELOAD`)
- **`pywhere.cpp`** - Python location tracking implementation
- **`get_line_atomic.cpp`** - Atomic line number access
- **`traceconfig.cpp`** - Trace configuration

### Vendor Libraries (`vendor/`)

- **`Heap-Layers/`** - Memory allocator infrastructure (by Emery Berger)
- **`printf/`** - Async-signal-safe printf implementation

## Key Patterns

### Python Version Compatibility

The codebase supports Python 3.8-3.14. Version-specific code uses:

```python
if sys.version_info >= (3, 14):
    # Python 3.14+ specific code
else:
    # Older Python versions
```

**Python 3.14 Changes:**
- `argparse` now has built-in colored help output (`color=True` parameter)
- `RichArgParser` uses Rich for colors on Python < 3.14, native argparse colors on 3.14+

### Argument Parsing (`scalene_parseargs.py`)

```python
class RichArgParser(argparse.ArgumentParser):
    """ArgumentParser that uses Rich for colored output on Python < 3.14."""

    def __init__(self, *args, **kwargs):
        if sys.version_info < (3, 14):
            from rich.console import Console
            self._console = Console()
        else:
            self._console = None
        super().__init__(*args, **kwargs)
```

The `_colorize_help_for_rich()` function applies Python 3.14-style colors using Rich markup:
- `usage:` and `options:` → bold blue
- Program name → bold magenta
- Long options (`--foo`) → bold cyan
- Short options (`-h`) → bold green
- Metavars (`FOO`) → bold yellow

### GUI Patterns

**Preventing Browser Password Prompts:**
Use `autocomplete="one-time-code"` on password/API key inputs to prevent browsers from offering to save them:
```html
<input type="password" id="api-key" autocomplete="one-time-code">
```

**Show/Hide Password Toggle:**
```typescript
function togglePassword(inputId: string, button: HTMLButtonElement): void {
  const input = document.getElementById(inputId) as HTMLInputElement;
  if (input.type === "password") {
    input.type = "text";
    button.textContent = "Hide";
  } else {
    input.type = "password";
    button.textContent = "Show";
  }
}
```

**Provider Field Visibility:**
Use CSS classes to show/hide provider-specific fields:
```typescript
function toggleServiceFields(): void {
  const service = (document.getElementById("service") as HTMLSelectElement).value;
  // Hide all provider sections
  document.querySelectorAll(".provider-section").forEach((el) => {
    (el as HTMLElement).style.display = "none";
  });
  // Show selected provider section
  const section = document.querySelector(`.${service}-fields`);
  if (section) (section as HTMLElement).style.display = "block";
}
```

**Persistent Form Elements:**
Add class `persistent` to inputs that should be saved/restored from localStorage:
```html
<input type="text" id="api-key" class="persistent">
```
The `persistence.ts` module handles save/restore automatically.

**Standalone HTML Generation:**
The `generate_html()` function in `scalene_utility.py` supports a `standalone` parameter:
- When `standalone=False` (default): Assets are referenced as local files (e.g., `<script src="jquery-3.6.0.slim.min.js">`)
- When `standalone=True`: All assets are embedded inline (JS/CSS as text, images as base64)

The Jinja2 template uses conditionals:
```html
{% if standalone %}
<script>{{ jquery_js }}</script>
<style>{{ bootstrap_css }}</style>
{% else %}
<script src="jquery-3.6.0.slim.min.js"></script>
<link href="bootstrap.min.css" rel="stylesheet">
{% endif %}
```

### Module Imports

When importing submodules, be explicit:

```python
# Correct - mypy can verify this
import importlib.util
importlib.util.find_spec(mod_name)

# Wrong - mypy error: Module has no attribute "util"
import importlib
importlib.util.find_spec(mod_name)
```

## Testing

### Test Files (`tests/`)

- **`test_coverup_*.py`** - Auto-generated coverage tests
- **`test_runningstats.py`** - Statistics tests (requires `hypothesis`)
- **`test_scalene_json.py`** - JSON output tests (requires `hypothesis`)
- **`test_nested_package_relative_import.py`** - Import handling tests

### Test Dependencies

```bash
pip install pytest pytest-asyncio hypothesis
```

### Running Tests Across Python Versions

```bash
for v in 3.9 3.10 3.11 3.12 3.13 3.14; do
    python$v -m pytest tests/test_coverup_83.py -v
done
```

### Flaky Smoketests

The smoketests in `test/` can be flaky due to timing/sampling issues inherent to profiling:

- **"No non-zero lines in X"** - The profiler didn't collect enough samples. This happens when the test runs too quickly or signal delivery timing varies.
- **"Expected function 'X' not returned"** - A function wasn't sampled. Common with short-running functions.

These failures are usually timing-related and pass on re-run. They're more common on CI due to variable machine load.

### Port Binding in Tests

When testing port availability, never use hardcoded ports - they may already be in use on CI runners:

```python
# Bad - port 49200 might be in use
port = 49200
sock.bind(("", port))

# Good - find an available port first
port = find_available_port(49200, 49300)
if port is None:
    return  # Skip test if no ports available
sock.bind(("", port))
```

## CI/CD (`.github/workflows/`)

- **`run-linters.yml`** - Runs mypy and ruff on Python 3.9-3.14
- **`tests.yml`** - Runs pytest on Python 3.9-3.14
- **`build-and-upload.yml`** - Build and publish to PyPI

## Common Tasks

### Adding a New CLI Option

1. Add default value in `scalene_arguments.py`:
   ```python
   class ScaleneArgumentsDict(TypedDict, total=False):
       my_option: bool
   ```

2. Add argument in `scalene_parseargs.py`:
   ```python
   parser.add_argument(
       "--my-option",
       dest="my_option",
       action="store_true",
       default=defaults.my_option,
       help="Description of option",
   )
   ```

### Adding a New AI Provider

1. **Create provider module** (`scalene/scalene-gui/newprovider.ts`):
   ```typescript
   export async function sendPromptToNewProvider(
     prompt: string,
     apiKey: string
   ): Promise<string> {
     // API call implementation
   }

   export async function fetchNewProviderModels(apiKey: string): Promise<string[]> {
     // Optional: fetch available models from API
   }
   ```

2. **Update `optimizations.ts`**:
   - Import the new module
   - Add case in `sendPromptToService()` switch statement

3. **Update `index.html.template`**:
   - Add option to `#service` select dropdown
   - Add provider section with API key input, model selector, etc.
   - Add CSS for `.newprovider-fields` visibility

4. **Update `scalene-gui.ts`**:
   - Add provider to `toggleServiceFields()` function
   - Add refresh handler if dynamic model fetching is supported
   - Update `getDefaultProvider()` if env var support is needed

5. **Update `persistence.ts`** (for env var support):
   - Add mapping in `envKeyMap` for new fields

6. **Update `scalene_utility.py`**:
   - Read environment variable in `api_keys` dict
   - Pass to template rendering

7. **Rebuild the bundle**:
   ```bash
   cd scalene/scalene-gui
   npx esbuild scalene-gui.ts --bundle --outfile=scalene-gui-bundle.js --format=iife --global-name=ScaleneGUI
   ```

### Environment Variable API Keys

The GUI supports prepopulating API keys from environment variables:

| Element ID | Environment Variable | Provider |
|------------|---------------------|----------|
| `api-key` | `OPENAI_API_KEY` | OpenAI |
| `anthropic-api-key` | `ANTHROPIC_API_KEY` | Anthropic |
| `gemini-api-key` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini |
| `azure-api-key` | `AZURE_OPENAI_API_KEY` | Azure OpenAI |
| `azure-api-url` | `AZURE_OPENAI_ENDPOINT` | Azure OpenAI |
| `aws-access-key` | `AWS_ACCESS_KEY_ID` | Amazon Bedrock |
| `aws-secret-key` | `AWS_SECRET_ACCESS_KEY` | Amazon Bedrock |
| `aws-region` | `AWS_DEFAULT_REGION` or `AWS_REGION` | Amazon Bedrock |

**Flow:**
1. `scalene_utility.py` reads env vars and passes to Jinja2 template
2. Template injects `envApiKeys` JavaScript object into page
3. `persistence.ts` uses env vars as fallbacks when localStorage is empty

### Updating Version

Edit `scalene/scalene_config.py`:
```python
scalene_version = "X.Y.Z"
scalene_date = "YYYY.MM.DD"
```

## Dependencies

Key runtime dependencies:
- `rich` - Terminal formatting and colors
- `cloudpickle` - Serialization
- `pynvml` - NVIDIA GPU support (optional)

See `requirements.txt` for full list.

## CLI Structure

Scalene uses a verb-based CLI with two main subcommands:

```bash
# Profile a program (saves to scalene-profile.json by default)
scalene run [options] yourprogram.py

# View an existing profile
scalene view [options] [profile.json]
```

### Run Subcommand Options

```bash
scalene run prog.py                      # profile, save to scalene-profile.json
scalene run -o my.json prog.py           # save to custom file
scalene run --cpu-only prog.py           # profile CPU only (faster)
scalene run -c config.yaml prog.py       # load options from config file
scalene run prog.py --- --arg            # pass args to program
```

### View Subcommand Options

```bash
scalene view                             # open in browser
scalene view --cli                       # view in terminal
scalene view --html                      # save to scalene-profile.html
scalene view --standalone                # save as self-contained HTML (all assets embedded)
scalene view myprofile.json              # open specific profile
```

### Profile Completion Message

After profiling completes, Scalene prints instructions for viewing the profile:
```
Scalene: profile saved to scalene-profile.json
  To view in browser:  scalene view
  To view in terminal: scalene view --cli
```

The filename is only included in the command if a non-default output file was used.

### YAML Configuration

Create a `scalene.yaml` file with options:

```yaml
outfile: my-profile.json
cpu-only: true
profile-only: "mypackage,utils"
cpu-percent-threshold: 5
```

Load with: `scalene run -c scalene.yaml prog.py`

### Advanced Options

Use `scalene run --help-advanced` to see all options including:
- `--profile-all` - profile all code, not just the target program
- `--profile-only PATH` - only profile files containing these strings
- `--profile-exclude PATH` - exclude files containing these strings
- `--profile-system-libraries` - profile Python stdlib and installed packages (skipped by default)
- `--gpu` - profile GPU time and memory
- `--memory` - profile memory usage
- `--stacks` - collect stack traces
- `--profile-interval N` - output profiles every N seconds

### Smoke Tests

Smoke tests in `test/` use the new CLI syntax:

```python
# test/smoketest.py
cmd = [sys.executable, "-m", "scalene", "run", "-o", str(outfile), *rest, fname]
```

### GitHub Workflows

Workflows in `.github/workflows/` use the new CLI:

```yaml
# Profile with interval, then view
- run: python -m scalene run --profile-interval=2 test/testme.py && python -m scalene view --cli

# Profile with module invocation
- run: python -m scalene run --- -m import_stress_test && python -m scalene view --cli
```

## Signal Handling

Scalene uses several Unix signals for profiling. The signal assignments are in `scalene_signals.py`:

| Signal | Purpose | Platform |
|--------|---------|----------|
| `SIGVTALRM` | CPU profiling timer (default) | Unix |
| `SIGALRM` | CPU profiling timer (real time mode) | Unix |
| `SIGILL` | Start profiling (`--on`) | Unix |
| `SIGBUS` | Stop profiling (`--off`) | Unix |
| `SIGPROF` | memcpy tracking | Unix |
| `SIGXCPU` | malloc tracking | Unix |
| `SIGXFSZ` | free tracking | Unix |

### Signal Conflicts with Libraries

Libraries like PyTorch Lightning may also use these signals. The `replacement_signal_fns.py` module handles conflicts:

**On Linux:** Uses real-time signals (`SIGRTMIN+1` to `SIGRTMIN+5`) for redirection. When user code sets a handler for a Scalene signal, their handler is redirected to a real-time signal. Calls to `raise_signal()` and `kill()` are also redirected transparently.

**On macOS/other platforms:** Uses handler chaining. Both Scalene's handler and the user's handler are called when the signal fires.

```python
# Platform-specific signal handling
_use_rt_signals = sys.platform == "linux" and hasattr(signal, "SIGRTMIN")

if _use_rt_signals:
    # Linux: redirect to real-time signals
    rt_base = signal.SIGRTMIN + 1
    _signal_redirects[signal.SIGILL] = rt_base
else:
    # macOS: chain handlers
    def chained_handler(sig, frame):
        scalene_handler(sig, frame)
        user_handler(sig, frame)
```

### Frame Line Number Can Be None (Python 3.11+)

In Python 3.11+, `frame.f_lineno` can be `None` in edge cases (e.g., during multiprocessing cleanup). Always use a fallback:

```python
lineno = frame.f_lineno if frame.f_lineno is not None else frame.f_code.co_firstlineno
```

## Native Extension Build Issues

### C++ Standard Library Conflicts with vendor/printf

The `vendor/printf/printf.h` header defines macros that conflict with C++ standard library:

```c
#define vsnprintf vsnprintf_
#define snprintf  snprintf_
```

This breaks `std::vsnprintf` in `<string>` and other headers. **Fix:** Include C++ standard headers BEFORE vendor headers in `src/source/libscalene.cpp`:

```cpp
// Include C++ standard headers FIRST
#include <cstddef>
#include <string>

// Then vendor headers that define conflicting macros
#include <heaplayers.h>  // Eventually includes printf.h
```

## Profiling Guide

See [Scalene-Agents.md](Scalene-Agents.md) for detailed information about interpreting Scalene's profiling output, including Python vs C time, memory metrics, and optimization strategies.
