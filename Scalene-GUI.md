# GUI Development Patterns

## Adding a New Column

1. **`gui-elements.ts`**: Add chart function (e.g., `makeAwaitPie`) following existing patterns
2. **`scalene-gui.ts`**:
   - Add to imports
   - Add chart array (e.g., `const await_pies: (unknown | null)[] = []`)
   - Add column in `makeTableHeader()`
   - Add cell rendering in `makeProfileLine()` — push chart specs to array
   - Pass array through both call sites (line profile loop + function profile loop)
   - Add `embedCharts(await_pies, "await_pie")` at the end
3. **Rebuild**: `npx esbuild scalene-gui.ts --bundle --outfile=scalene-gui-bundle.js --format=iife --global-name=ScaleneGUI`
4. **`scalene_json.py`**: Add field to `FunctionDetail`, compute in payload
5. **`scalene_output.py`**: Add column for CLI `--html` output
6. **`scalene_parseargs.py`**: Add column in `_display_profile_cli()` for `scalene view --cli`

## Chart Types (Vega-Lite)

All charts are Vega-Lite specs rendered via `vegaEmbed()` after DOM insertion.

- **Bar**: `makeBar()` — stacked horizontal bar (CPU time: Python/native/system)
- **Pie**: `makeGPUPie()`, `makeAwaitPie()`, `makeMemoryPie()` — arc charts
- **Sparkline**: `makeSparkline()` — line chart for memory timeline
- **NRT/NC bars**: `makeNRTBar()`, `makeNCTimeBar()` — Neuron time bars
- **Standard dimensions**: 20px height, various widths

## Pie Chart Best Practices

- Always use **two data values** (filled + remaining) for a complete circle. Single-value pies with `scale: { domain: [0, 100] }` show partial arcs with gaps — looks bad.
- For **rotating pies** (each row's wedge starts where previous ended): use `scale: { range: [startAngle, startAngle + 2*PI] }` on the theta encoding. Track cumulative angle:
  ```typescript
  pieAngles.await += (pct / 100) * 2 * Math.PI;
  ```
- Reset angle state per table (line profile and function profile tables get separate `pieAngles` objects).

## Chart Rendering Flow

1. `makeProfileLine()` builds HTML string with `<span id="chart_name${index}">` placeholders
2. Chart specs are pushed to arrays (e.g., `cpu_bars`, `gpu_pies`, `await_pies`)
3. After all HTML is inserted into DOM, `embedCharts(array, "prefix")` calls `vegaEmbed()` for each spec
4. SVGs render asynchronously — Selenium tests need explicit waits to verify SVG content

## makeProfileLine Call Sites

This function has many parameters. When adding new ones, append to the end with defaults. The two call sites are:
- Line profile loop: creates `linePieAngles = { await: 0, gpu: 0 }` before the loop
- Function profile loop: creates `fnPieAngles = { await: 0, gpu: 0 }` before the loop
