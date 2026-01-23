import { Buffer } from "buffer";
(window as unknown as { Buffer: typeof Buffer }).Buffer = Buffer;
import vegaEmbed from "vega-embed";

import { Prism } from "./prism";
import Tablesort from "./tablesort";
import { proposeOptimization } from "./optimizations";
import { unescapeUnicode, memory_consumed_str, time_consumed_str } from "./utils";
import {
  makeBar,
  makeGPUPie,
  makeMemoryPie,
  makeMemoryBar,
  makeSparkline,
  makeNRTBar,
  makeNCTimeBar,
  makeTotalNeuronBar,
  Lightning,
  Explosion,
  RightTriangle,
  DownTriangle,
  WhiteLightning,
  WhiteExplosion,
} from "./gui-elements";
import { checkApiKey, fetchOpenAIModels } from "./openai";
import { fetchGeminiModels } from "./gemini";
import { fetchModelNames } from "./ollama";
import { observeDOM, processPersistentElements } from "./persistence";

// Expose checkApiKey globally
(window as unknown as { checkApiKey: typeof checkApiKey }).checkApiKey = checkApiKey;

// Type declarations
declare const example_profile: Profile;
declare const profile: Profile;

interface LineData {
  lineno: number;
  line: string;
  n_cpu_percent_python: number;
  n_cpu_percent_c: number;
  n_sys_percent: number;
  n_core_utilization: number;
  n_peak_mb: number;
  n_avg_mb: number;
  n_python_fraction: number;
  n_copy_mb_s: number;
  n_copy_mb: number;
  n_gpu_percent: number;
  n_gpu_peak_memory_mb: number;
  n_usage_fraction: number;
  n_malloc_mb: number;
  memory_samples: [number, number][];
  start_region_line: number;
  end_region_line: number;
  start_function_line: number;
  end_function_line: number;
  nrt_time_ms?: number;
  nrt_percent?: number;
  nc_time_ms?: number;
  cpu_samples_nc_overlap_percent?: number;
}

interface FunctionData extends LineData {}

interface FileData {
  lines: LineData[];
  functions: FunctionData[];
  imports: string[];
  percent_cpu_time: number;
  leaks?: Record<number, { velocity_mb_s: number }>;
}

interface Profile {
  files: Record<string, FileData>;
  gpu: boolean;
  gpu_device: string;
  memory: boolean;
  max_footprint_mb: number;
  elapsed_time_sec: number;
  samples: [number, number][];
  growth_rate: number;
  program?: string;
  stacks?: unknown;
}

interface Column {
  title: [string, string];
  color: string;
  width: number;
  info?: string;
}

interface TableParams {
  functions: boolean;
}

declare const globalThis: {
  profile: Profile;
};

export function vsNavigate(filename: string, lineno: number): void {
  // If we are in VS Code, clicking on a line number in Scalene's web UI will navigate to that line in the source code.
  try {
    const vscode = (window as unknown as { acquireVsCodeApi: () => { postMessage: (msg: unknown) => void } }).acquireVsCodeApi();
    vscode.postMessage({
      command: "jumpToLine",
      filePath: filename,
      lineNumber: lineno,
    });
  } catch {
    // Do nothing
  }
}

const maxLinesPerRegion = 50; // Only show regions that are no more than this many lines.

let showedExplosion: Record<string, boolean> = {}; // Used so we only show one explosion per region.

export function proposeOptimizationRegion(
  filename: string,
  file_number: number,
  line: string
): void {
  proposeOptimization(
    filename,
    file_number,
    JSON.parse(decodeURIComponent(line)),
    { regions: true }
  );
}

export function proposeOptimizationLine(
  filename: string,
  file_number: number,
  line: string
): void {
  proposeOptimization(
    filename,
    file_number,
    JSON.parse(decodeURIComponent(line)),
    { regions: false }
  );
}

const CPUColor = "blue";
const MemoryColor = "green";
const CopyColor = "goldenrod";
let columns: Column[] = [];

function stringLines(lines: string[]): Set<number> {
  const docstringLines = new Set<number>();

  let inDocstring = false;
  let docstringDelimiter: string | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let searchIndex = 0;
    const wasInDocstring = inDocstring;

    while (true) {
      const nextTripleSingle = line.indexOf("'''", searchIndex);
      const nextTripleDouble = line.indexOf('"""', searchIndex);

      let nextIndex = -1;
      let foundDelimiter: string | null = null;

      if (
        nextTripleSingle !== -1 &&
        (nextTripleDouble === -1 || nextTripleSingle < nextTripleDouble)
      ) {
        nextIndex = nextTripleSingle;
        foundDelimiter = "'''";
      } else if (
        nextTripleDouble !== -1 &&
        (nextTripleSingle === -1 || nextTripleDouble < nextTripleSingle)
      ) {
        nextIndex = nextTripleDouble;
        foundDelimiter = '"""';
      }

      if (nextIndex === -1) {
        break;
      }

      searchIndex = nextIndex + 3;

      if (!inDocstring) {
        inDocstring = true;
        docstringDelimiter = foundDelimiter;
      } else {
        if (docstringDelimiter === foundDelimiter) {
          inDocstring = false;
          docstringDelimiter = null;
        }
      }
    }

    if (wasInDocstring || inDocstring) {
      docstringLines.add(i);
    }
  }
  return docstringLines;
}

function makeTableHeader(
  fname: string,
  gpu: boolean,
  gpu_device: string,
  memory: boolean,
  params: TableParams,
  hasNeuronData: boolean
): string {
  let tableTitle: string;
  if (params["functions"]) {
    tableTitle = "function profile";
  } else {
    tableTitle = "line profile";
  }
  columns = [
    {
      title: ["time", ""],
      color: CPUColor,
      width: 0,
      info: "Execution time (Python + native + system)",
    },
  ];

  if (hasNeuronData) {
    columns.push({
      title: ["Unused Device", "%"],
      color: "darkred",
      width: 0,
      info: "Percentage of CPU samples where device was not being utilized concurrently",
    });
  }

  if (memory) {
    columns = columns.concat([
      {
        title: ["memory", "peak"],
        color: MemoryColor,
        width: 0,
        info: "Peak amount of memory allocated by line / function",
      },
      {
        title: ["memory", "average"],
        color: MemoryColor,
        width: 0,
        info: "Average amount of memory allocated by line / function",
      },
      {
        title: ["memory", "timeline"],
        color: MemoryColor,
        width: 0,
        info: "Memory footprint over time",
      },
      {
        title: ["memory", "activity"],
        color: MemoryColor,
        width: 0,
        info: "% of bytes allocated by line / function over total bytes allocated in file",
      },
      {
        title: ["copy", ""],
        color: CopyColor,
        width: 0,
        info: "Rate of copying memory",
      },
    ]);
  }
  if (gpu && !hasNeuronData) {
    columns.push({
      title: [gpu_device, "util."],
      color: CopyColor,
      width: 0,
      info: `% utilization of ${gpu_device} by line / function (may be inaccurate if ${gpu_device} is not dedicated)`,
    });
    columns.push({
      title: [gpu_device, "memory"],
      color: CopyColor,
      width: 0,
      info: `Peak ${gpu_device} memory allocated by line / function (may be inaccurate if ${gpu_device} is not dedicated)`,
    });
  }
  if (hasNeuronData) {
    columns.push({
      title: ["NRT", "%"],
      color: "purple",
      width: 0,
      info: "Neural Runtime percentage",
    });
    columns.push({
      title: ["NC", "time"],
      color: "darkorange",
      width: 0,
      info: "Neuron Compute time",
    });
  }
  columns.push({ title: ["", ""], color: "black", width: 100 });

  let s = "";
  s += '<thead class="thead-light">';
  s += '<tr data-sort-method="thead">';
  for (const col of columns) {
    s += `<th class="F${escape(
      fname
    )}-nonline"><font style="font-variant: small-caps; text-decoration: underline; width:${
      col.width
    }" color=${col.color}>`;
    if (col.info) {
      s += `<a style="cursor:pointer;" title="${col.info}">${col.title[0]}</a>`;
    } else {
      s += `<a style="cursor:pointer;">${col.title[0]}</a>`;
    }
    s += "</font>&nbsp;&nbsp;</th>";
  }
  let id: string;
  if (params["functions"]) {
    id = "functionProfile";
  } else {
    id = "lineProfile";
  }
  s += `<th id=${
    escape(fname) + "-" + id
  } style="width:10000"><font style="font-variant: small-caps; text-decoration: underline">${tableTitle}</font><font style="font-size:small; font-style: italic">&nbsp; (click to reset order)</font></th>`;
  s += "</tr>";
  s += '<tr data-sort-method="thead">';
  for (const col of columns) {
    s += `<th style="width:${col.width}"><em><font style="font-size: small" color=${col.color}>${col.title[1]}</font></em></th>`;
  }
  s += `<th><code>${fname}</code></th></tr>`;
  s += "</thead>";
  return s;
}

// Display mode constants
type DisplayMode = "all" | "profiled-lines" | "profiled-functions";

// Apply display mode for a specific file
export function applyFileDisplayMode(fileId: string, mode: DisplayMode): void {
  const rows = document.querySelectorAll(`tr[data-file="${fileId}"]`) as NodeListOf<HTMLElement>;

  for (const row of rows) {
    if (mode === "all") {
      // Show everything
      row.style.display = "";
    } else if (mode === "profiled-lines") {
      // Show only lines with profiling data
      if (row.classList.contains("empty-profile") || row.classList.contains("function-context")) {
        row.style.display = "none";
      } else {
        row.style.display = "";
      }
    } else {
      // profiled-functions: show profiled lines + function context
      if (row.classList.contains("empty-profile")) {
        row.style.display = "none";
      } else {
        row.style.display = "";
      }
    }
  }
}

export function onFileDisplayModeChange(fileId: string): void {
  const select = document.getElementById(`display-mode-${fileId}`) as HTMLSelectElement | null;
  if (select) {
    applyFileDisplayMode(fileId, select.value as DisplayMode);
  }
}

// Legacy support for old checkbox toggle (now does nothing)
export function toggleReduced(): void {
  // No-op for backwards compatibility
}

function makeProfileLine(
  line: LineData,
  inDocstring: boolean,
  filename: string,
  file_number: number,
  prof: Profile,
  cpu_bars: (unknown | null)[],
  memory_bars: (unknown | null)[],
  memory_sparklines: (unknown | null)[],
  memory_activity: (unknown | null)[],
  gpu_pies: (unknown | null)[],
  propose_optimizations: boolean,
  nrt_bars: (unknown | null)[],
  nc_bars: (unknown | null)[],
  nc_nrt_pies: (unknown | null)[],
  total_nc_time_for_file: number,
  hasNeuronData: boolean,
  profiledFunctions: Set<string> = new Set()
): string {
  let total_time =
    line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;
  let total_region_time = 0;
  let region_has_memory_results = 0;
  let region_has_gpu_results = false;

  for (
    let lineno = line.start_region_line;
    lineno < line.end_region_line;
    lineno++
  ) {
    const currline = prof["files"][filename]["lines"][lineno];
    total_region_time +=
      currline.n_cpu_percent_python +
      currline.n_cpu_percent_c +
      currline.n_sys_percent;
    region_has_memory_results +=
      currline.n_avg_mb +
      currline.n_peak_mb +
      currline.memory_samples.length +
      (currline.n_usage_fraction >= 0.01 ? 1 : 0);
    region_has_gpu_results = region_has_gpu_results || line.n_gpu_percent >= 1.0;
  }

  if (propose_optimizations) {
    if (total_time < 1.0 && line.start_region_line === line.end_region_line) {
      propose_optimizations = false;
    }
    if (line.start_region_line !== line.end_region_line) {
      if (total_region_time < 1.0) {
        propose_optimizations = false;
      }
    }
  }

  const has_memory_results =
    line.n_avg_mb +
    line.n_peak_mb +
    line.memory_samples.length +
    (line.n_usage_fraction >= 0.01 ? 1 : 0);
  const has_gpu_results = line.n_gpu_percent >= 1.0;
  const has_nrt_results =
    (line.nrt_time_ms !== undefined && line.nrt_time_ms > 0) ||
    (line.nc_time_ms !== undefined && line.nc_time_ms > 0);
  const start_region_line = line.start_region_line;
  const end_region_line = line.end_region_line;

  let explosionString: string;
  let showExplosion: boolean;
  const regionKey = `${start_region_line - 1},${end_region_line}`;

  if (
    start_region_line === end_region_line ||
    regionKey in showedExplosion
  ) {
    explosionString = WhiteExplosion;
    showExplosion = false;
  } else {
    explosionString = Explosion;
    if (start_region_line && end_region_line) {
      showedExplosion[regionKey] = true;
      showExplosion = true;
    } else {
      showExplosion = false;
    }
  }

  showExplosion = showExplosion && end_region_line - start_region_line <= maxLinesPerRegion;

  // Determine if this line has profiling data
  const hasProfileData =
    total_time > 1.0 ||
    has_memory_results ||
    (has_gpu_results && prof.gpu && !hasNeuronData) ||
    has_nrt_results ||
    (showExplosion &&
      start_region_line !== end_region_line &&
      (total_region_time >= 1.0 ||
        region_has_memory_results ||
        (region_has_gpu_results && prof.gpu && !hasNeuronData)));

  // Determine if this line is in a profiled function/class
  const functionKey = line.start_function_line > 0
    ? `${line.start_function_line},${line.end_function_line}`
    : "";
  const inProfiledFunction = functionKey !== "" && profiledFunctions.has(functionKey);

  // Classify the line:
  // - hasProfileData: always visible
  // - inProfiledFunction but no data: function-context (visible in "profiled functions" mode)
  // - not in profiled function and no data: empty-profile (only visible in "all" mode)
  let s = "";
  let rowClass = "";
  if (!hasProfileData) {
    if (inProfiledFunction) {
      rowClass = "function-context";
    } else {
      rowClass = "empty-profile";
    }
  }
  const fileId = `file-${file_number}`;
  s += `<tr class="${rowClass}" data-file="${fileId}">`;

  const total_time_str = String(total_time.toFixed(1)).padStart(10, " ");
  s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${total_time_str}'>`;
  s += `<span style="height: 20; width: 100; vertical-align: middle" id="cpu_bar${cpu_bars.length}"></span>`;
  if (total_time) {
    cpu_bars.push(
      makeBar(
        line.n_cpu_percent_python,
        line.n_cpu_percent_c,
        line.n_sys_percent,
        { height: 20, width: 100 }
      )
    );
  } else {
    cpu_bars.push(null);
  }
  s += "</td>";

  if (hasNeuronData) {
    if (
      (total_time >= 1.0 || has_nrt_results) &&
      line.cpu_samples_nc_overlap_percent !== undefined
    ) {
      const overlap_percent = line.cpu_samples_nc_overlap_percent || 0;
      const unused_percent = 100 - overlap_percent;
      let color = "green";
      if (unused_percent >= 60) {
        color = "darkred";
      } else if (unused_percent >= 30) {
        color = "goldenrod";
      }

      s += `<td style="width: 100; vertical-align: middle; padding-right: 8px;" align="right" data-sort='${unused_percent.toFixed(
        1
      )}'>`;
      s += `<font style="font-size: small" color="${color}">${unused_percent.toFixed(
        1
      )}%&nbsp;&nbsp;&nbsp;</font>`;
      s += "</td>";
    } else {
      s += '<td style="width: 100; padding-right: 8px;"></td>';
    }
  }

  if (prof.memory) {
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_peak_mb.toFixed(0)
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    if (line.n_peak_mb) {
      memory_bars.push(
        makeMemoryBar(
          line.n_peak_mb.toFixed(0),
          "peak memory",
          parseFloat(String(line.n_python_fraction)),
          prof.max_footprint_mb.toFixed(2),
          "darkgreen",
          { height: 20, width: 100 }
        )
      );
    } else {
      memory_bars.push(null);
    }
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_avg_mb.toFixed(0)
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    s += "</td>";
    if (line.n_avg_mb) {
      memory_bars.push(
        makeMemoryBar(
          line.n_avg_mb.toFixed(0),
          "average memory",
          parseFloat(String(line.n_python_fraction)),
          prof.max_footprint_mb.toFixed(2),
          "darkgreen",
          { height: 20, width: 100 }
        )
      );
    } else {
      memory_bars.push(null);
    }
    s += "</td>";
    s += `<td style='vertical-align: middle; width: 100'><span style="height:20; width: 100; vertical-align: middle" id="memory_sparkline${memory_sparklines.length}"></span>`;
    s += "</td>";
    if (line.memory_samples.length > 0) {
      let leak_velocity = 0;
      if ("leaks" in prof.files[filename]) {
        const leaks = prof.files[filename].leaks;
        if (leaks && line.lineno in leaks) {
          leak_velocity = leaks[line.lineno].velocity_mb_s;
        }
      }
      memory_sparklines.push(
        makeSparkline(
          line.memory_samples,
          prof.elapsed_time_sec * 1e9,
          prof.max_footprint_mb,
          leak_velocity,
          { height: 20, width: 75 }
        )
      );
    } else {
      memory_sparklines.push(null);
    }
    s += '<td style="width: 100; vertical-align: middle" align="center">';
    if (line.n_usage_fraction >= 0.01) {
      s += `<span style="height: 20; width: 30; vertical-align: middle" id="memory_activity${memory_activity.length}"></span>`;
      memory_activity.push(
        makeMemoryPie(
          100 *
            line.n_usage_fraction *
            (1 - parseFloat(String(line.n_python_fraction))),
          100 * line.n_usage_fraction * parseFloat(String(line.n_python_fraction)),
          { width: 30 }
        )
      );
    } else {
      memory_activity.push(null);
    }
    s += "</td>";
    if (line.n_copy_mb_s < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${line.n_copy_mb_s.toFixed(
        0
      )}&nbsp;&nbsp;&nbsp;</font></td>`;
    }
  }
  if (prof.gpu && !hasNeuronData) {
    if (line.n_gpu_percent < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      s += `<td style="width: 50; vertical-align: middle" align="right" data-sort="${line.n_gpu_percent}">`;
      s += `<span style="height: 20; width: 30; vertical-align: middle" id="gpu_pie${gpu_pies.length}"></span>`;
      s += "</td>";
      gpu_pies.push(
        makeGPUPie(line.n_gpu_percent, prof.gpu_device, {
          height: 20,
          width: 30,
        })
      );
    }
    if (line.n_gpu_peak_memory_mb < 1.0 || line.n_gpu_percent < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      let mem = line.n_gpu_peak_memory_mb;
      let memStr = "MB";
      if (mem >= 1024) {
        mem /= 1024;
        memStr = "GB";
      }
      s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${mem.toFixed(
        0
      )}${memStr}&nbsp;&nbsp;</font></td>`;
    }
  }

  if (hasNeuronData) {
    if (
      (line.nrt_time_ms !== undefined && line.nrt_time_ms > 0) ||
      (line.nrt_percent !== undefined && line.nrt_percent > 0)
    ) {
      const sortValue = line.nrt_time_ms || line.nrt_percent || 0;
      s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${sortValue.toFixed(
        1
      )}'>`;
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nrt_bar${nrt_bars.length}"></span>`;
      s += "</td>";
      nrt_bars.push(
        makeNRTBar(line.nrt_time_ms || 0, prof.elapsed_time_sec, {
          height: 20,
          width: 100,
        })
      );
    } else {
      s += '<td style="width: 100"></td>';
      nrt_bars.push(null);
    }

    if (line.nc_time_ms !== undefined && line.nc_time_ms > 0) {
      s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${line.nc_time_ms.toFixed(
        1
      )}'>`;
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nc_bar${nc_bars.length}"></span>`;
      s += "</td>";
      nc_bars.push(
        makeNCTimeBar(line.nc_time_ms, prof.elapsed_time_sec, {
          height: 20,
          width: 100,
        })
      );
    } else {
      s += '<td style="width: 100"></td>';
      nc_bars.push(null);
    }
  }

  const empty_profile =
    total_time ||
    has_memory_results ||
    (has_gpu_results && prof.gpu && !hasNeuronData) ||
    has_nrt_results ||
    end_region_line !== start_region_line
      ? ""
      : "empty-profile";
  s += `<td align="right" class="dummy ${empty_profile}" style="vertical-align: middle; width: 50" data-sort="${line.lineno}"><span onclick="vsNavigate('${escape(filename)}',${line.lineno})"><font color="gray" style="font-size: 70%; vertical-align: middle" >${line.lineno}&nbsp;</font></span></td>`;

  const regionOptimizationString =
    propose_optimizations && showExplosion
      ? `${explosionString}&nbsp;`
      : `${WhiteExplosion}&nbsp;`;

  // Convert back any escaped Unicode.
  line.line = unescapeUnicode(line.line);

  const codeLine = Prism.highlight(line.line, Prism.languages.python, "python");

  // If we are in a docstring, format it as such in the <span>
  let optionalInDocstring = "";
  if (inDocstring) {
    optionalInDocstring = "token comment";
  }

  s += `<td style="height:10" align="left" bgcolor="whitesmoke" style="vertical-align: middle" data-sort="${line.lineno}">`;
  const newLine = structuredClone(line);

  if (propose_optimizations && showExplosion) {
    // Construct a new line corresponding to this region.
    let mb_copied = 0;
    for (let lineno = start_region_line; lineno < end_region_line; lineno++) {
      const currline = prof["files"][filename]["lines"][lineno];
      mb_copied += currline.n_copy_mb * prof.elapsed_time_sec;
      newLine.n_cpu_percent_python += currline.n_cpu_percent_python;
      newLine.n_cpu_percent_c += currline.n_cpu_percent_c;
      newLine.n_sys_percent += currline.n_sys_percent;
      newLine.n_gpu_percent += currline.n_gpu_percent;
      if (currline.n_peak_mb > newLine.n_peak_mb) {
        newLine.n_peak_mb = currline.n_peak_mb;
        newLine.n_python_fraction = currline.n_python_fraction;
      }
      newLine.n_core_utilization +=
        (currline.n_cpu_percent_python + currline.n_cpu_percent_c) *
        currline.n_core_utilization;
    }
    newLine.n_copy_mb_s = mb_copied / prof.elapsed_time_sec;
    s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for the entire region starting here." onclick="proposeOptimizationRegion('${escape(
      filename
    )}', ${file_number}, '${encodeURIComponent(
      JSON.stringify(newLine)
    )}'); event.preventDefault()">${regionOptimizationString}</span>`;
  } else {
    s += regionOptimizationString;
  }

  const lineOptimizationString = propose_optimizations
    ? `${Lightning}`
    : `${WhiteLightning}`;
  if (propose_optimizations) {
    s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for this line." onclick="proposeOptimizationLine('${escape(
      filename
    )}', ${file_number}, '${encodeURIComponent(
      JSON.stringify(line)
    )}'); event.preventDefault()">${lineOptimizationString}</span>`;
  } else {
    s += lineOptimizationString;
  }
  s += `<pre style="height: 10; display: inline; white-space: pre-wrap; overflow-x: auto; border: 0px; vertical-align: middle"><code class="language-python ${optionalInDocstring} ${empty_profile}">${codeLine}<span id="code-${file_number}-${line.lineno}" bgcolor="white"></span></code></pre></td>`;
  s += "</tr>";
  return s;
}

// Track all profile ids so we can collapse and expand them en masse.
let allIds: string[] = [];

export function collapseAll(): void {
  for (const id of allIds) {
    collapseDisplay(id);
  }
}

export function expandAll(): void {
  for (const id of allIds) {
    expandDisplay(id);
  }
}

function collapseDisplay(id: string): void {
  const d = document.getElementById(`profile-${id}`);
  if (d) {
    d.style.display = "none";
  }
  const btn = document.getElementById(`button-${id}`);
  if (btn) {
    btn.innerHTML = RightTriangle;
  }
}

function expandDisplay(id: string): void {
  const d = document.getElementById(`profile-${id}`);
  if (d) {
    d.style.display = "block";
  }
  const btn = document.getElementById(`button-${id}`);
  if (btn) {
    btn.innerHTML = DownTriangle;
  }
}

export function toggleDisplay(id: string): void {
  const d = document.getElementById(`profile-${id}`);
  if (d) {
    if (d.style.display === "block") {
      d.style.display = "none";
      const btn = document.getElementById(`button-${id}`);
      if (btn) {
        btn.innerHTML = RightTriangle;
      }
    } else {
      d.style.display = "block";
      const btn = document.getElementById(`button-${id}`);
      if (btn) {
        btn.innerHTML = DownTriangle;
      }
    }
  }
}

// Extend String prototype
declare global {
  interface String {
    padWithNonBreakingSpaces(targetLength: number): string;
  }
}

String.prototype.padWithNonBreakingSpaces = function (
  targetLength: number
): string {
  const nbsp = "&nbsp;";
  let padding = "";
  let currentLength = this.length * nbsp.length;
  targetLength *= nbsp.length;

  while (currentLength < targetLength) {
    padding += nbsp;
    currentLength += nbsp.length;
  }

  return padding + this;
};

async function display(prof: Profile): Promise<void> {
  // Clear explosions.
  showedExplosion = {};

  // Compute overall usage and detect neuron data FIRST
  let cpu_python = 0;
  let cpu_native = 0;
  let cpu_system = 0;
  let mem_python = 0;
  let max_alloc = 0;
  const cp: Record<string, number> = {};
  const cn: Record<string, number> = {};
  const cs: Record<string, number> = {};
  const mp: Record<string, number> = {};
  const ma: Record<string, number> = {};
  const total_nc_time: Record<string, number> = {};
  const total_nrt_time: Record<string, number> = {};
  let hasNeuronData = false;

  for (const f in prof.files) {
    cp[f] = 0;
    cn[f] = 0;
    cs[f] = 0;
    mp[f] = 0;
    ma[f] = 0;
    total_nc_time[f] = 0;
    total_nrt_time[f] = 0;
    for (const l in prof.files[f].lines) {
      const line = prof.files[f].lines[l];
      cp[f] += line.n_cpu_percent_python;
      cn[f] += line.n_cpu_percent_c;
      cs[f] += line.n_sys_percent;
      if (line.n_peak_mb > ma[f]) {
        ma[f] = line.n_peak_mb;
        mp[f] += line.n_peak_mb * line.n_python_fraction;
      }
      max_alloc += line.n_malloc_mb;
      if (line.nc_time_ms !== undefined && line.nc_time_ms > 0) {
        total_nc_time[f] += line.nc_time_ms;
        hasNeuronData = true;
      }
      if (line.nrt_time_ms !== undefined && line.nrt_time_ms > 0) {
        total_nrt_time[f] += line.nrt_time_ms;
        hasNeuronData = true;
      }
      if (line.nrt_percent !== undefined && line.nrt_percent > 0) {
        hasNeuronData = true;
      }
    }
    cpu_python += cp[f];
    cpu_native += cn[f];
    cpu_system += cs[f];
    mem_python += mp[f];
  }

  // Restore the API key from local storage (if any).
  const old_key = window.localStorage.getItem("scalene-api-key");

  if (old_key) {
    const apiKeyElement = document.getElementById("api-key") as HTMLInputElement | null;
    if (apiKeyElement) {
      apiKeyElement.value = old_key;
    }
    // Update the status.
    checkApiKey(old_key);
  }

  const selectedService = window.localStorage.getItem("scalene-service-select");
  if (selectedService) {
    const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
    if (serviceSelect) {
      serviceSelect.value = selectedService;
    }
    toggleServiceFields();
  }

  const gpu_checkbox = document.getElementById("use-gpu-checkbox") as HTMLInputElement | null;
  if (gpu_checkbox && gpu_checkbox.checked !== prof.gpu) {
    gpu_checkbox.click();
  }
  if (prof.gpu) {
    const acceleratorName = document.getElementById("accelerator-name");
    if (acceleratorName) {
      acceleratorName.innerHTML = prof.gpu_device;
    }
  }
  globalThis.profile = prof;
  const memory_sparklines: (unknown | null)[] = [];
  const memory_activity: (unknown | null)[] = [];
  const gpu_pies: (unknown | null)[] = [];
  const memory_bars: (unknown | null)[] = [];
  const nrt_bars: (unknown | null)[] = [];
  const nc_bars: (unknown | null)[] = [];
  const nc_nrt_pies: (unknown | null)[] = [];
  let tableID = 0;
  let s = "";
  s += '<span class="row justify-content-center">';
  s += '<span class="col-auto">';
  s += '<table width="50%" class="table text-center table-condensed">';
  s += "<tr>";
  s += `<td><font style="font-size: small"><b>Time:</b> <font color="darkblue">Python</font> | <font color="#6495ED">native</font> | <font color="blue">system</font><br /></font></td>`;
  s += '<td width="10"></td>';
  if (prof.memory) {
    s += `<td><font style="font-size: small"><b>Memory:</b> <font color="darkgreen">Python</font> | <font color="#50C878">native</font><br /></font></td>`;
    s += '<td width="10"></td>';
    s += '<td valign="middle" style="vertical-align: middle">';
    s += `<font style="font-size: small"><b>Memory timeline: </b>(max: ${memory_consumed_str(
      prof.max_footprint_mb
    )}, growth: ${prof.growth_rate.toFixed(1)}%)</font>`;
    s += "</td>";
  }
  s += "</tr>";
  s += "<tr>";
  s +=
    '<td height="10"><span style="height: 20; width: 200; vertical-align: middle" id="cpu_bar0"></span></td>';
  s += "<td></td>";
  if (prof.memory) {
    s +=
      '<td height="20"><span style="height: 20; width: 150; vertical-align: middle" id="memory_bar0"></span></td>';
    s += "<td></td>";
    s +=
      '<td align="left"><span style="vertical-align: middle" id="memory_sparkline0"></span></td>';
    memory_sparklines.push(
      makeSparkline(
        prof.samples,
        prof.elapsed_time_sec * 1e9,
        prof.max_footprint_mb,
        0,
        { height: 20, width: 200 }
      )
    );
  }
  s += "</tr>";

  const cpu_bars: (unknown | null)[] = [];
  cpu_bars.push(
    makeBar(cpu_python, cpu_native, cpu_system, { height: 20, width: 200 })
  );
  if (prof.memory) {
    memory_bars.push(
      makeMemoryBar(
        prof.max_footprint_mb.toFixed(2),
        "memory",
        mem_python / max_alloc,
        prof.max_footprint_mb.toFixed(2),
        "darkgreen",
        { height: 20, width: 150 }
      )
    );
  }

  s += '<tr><td colspan="10">';
  s += `<span class="text-center"><font style="font-size: 90%; font-style: italic; font-color: darkgray">hover over bars to see breakdowns; click on <font style="font-variant:small-caps; text-decoration:underline">column headers</font> to sort.</font></span>`;
  s += "</td></tr>";
  s += "</table>";
  s += "</span>";
  s += "</span>";

  if (JSON.stringify(prof) === "{}") {
    // Empty profile.
    s += `
    <form id="jsonFile" name="jsonFile" enctype="multipart/form-data" method="post">
      <div class="form-group">
	<div class="d-flex justify-content-center">
	  <label for='fileinput' style="padding: 5px 5px; border-radius: 5px; border: 1px ridge black; font-size: 0.8rem; height: auto;">Select a profile (.json)</label>
	  <input style="height: 0; width: 10; opacity:0" type='file' id='fileinput' accept='.json' onchange="loadFile();">
	</div>
      </div>
    </form>
    </div>`;
    const p = document.getElementById("profile");
    if (p) {
      p.innerHTML = s;
    }
    return;
  }

  s +=
    '<br class="text-left"><span style="font-size: 80%; color: blue; cursor : pointer;" onClick="expandAll()">&nbsp;show all</span> | <span style="font-size: 80%; color: blue; cursor : pointer;" onClick="collapseAll()">hide all</span></br>';

  s += '<div class="container-fluid">';

  // Convert files to an array and sort it in descending order by percent of CPU time.
  let files = Object.entries(prof.files);
  files.sort((x, y) => {
    return y[1].percent_cpu_time - x[1].percent_cpu_time;
  });

  // Print profile for each file
  let fileIteration = 0;
  allIds = [];
  const excludedFiles = new Set<[string, FileData]>();
  for (const ff of files) {
    fileIteration++;
    // Stop once total CPU time / memory consumption are below some threshold (1%)
    if (ff[1].percent_cpu_time < 1.0 && ma[ff[0]] < 0.01 * max_alloc) {
      excludedFiles.add(ff);
      continue;
    }
    const id = `file-${fileIteration}`;
    allIds.push(id);
    s +=
      '<p class="text-left sticky-top bg-white bg-opacity-75" style="backdrop-filter: blur(2px)">';
    let displayStr = "display:block;";
    let triangle = DownTriangle;
    if (fileIteration !== 1) {
      displayStr = "display:none;";
      triangle = RightTriangle;
    }

    s += `<span style="height: 20; width: 100; vertical-align: middle" id="cpu_bar${cpu_bars.length}"></span>&nbsp;`;
    cpu_bars.push(
      makeBar(cp[ff[0]], cn[ff[0]], cs[ff[0]], { height: 20, width: 100 })
    );
    if (prof.memory) {
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
      memory_bars.push(
        makeMemoryBar(
          ma[ff[0]],
          "peak memory",
          mp[ff[0]] / ma[ff[0]],
          prof.max_footprint_mb.toFixed(2),
          "darkgreen",
          { height: 20, width: 100 }
        )
      );
    }
    s += `<font style="font-size: 90%">% of time = ${ff[1].percent_cpu_time
      .toFixed(1)
      .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
      (ff[1].percent_cpu_time / 100.0) * prof.elapsed_time_sec * 1e3
    ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
      prof.elapsed_time_sec * 1e3
    ).padWithNonBreakingSpaces(8)})`;

    if (hasNeuronData && total_nrt_time[ff[0]] > 0) {
      s += `<br /><span style="height: 20; width: 100; vertical-align: middle" id="nrt_bar${nrt_bars.length}"></span>&nbsp;`;
      nrt_bars.push(
        makeTotalNeuronBar(total_nrt_time[ff[0]], prof.elapsed_time_sec, "NRT", "purple", {
          height: 20,
          width: 100,
        })
      );
      const nrt_percent =
        (total_nrt_time[ff[0]] / 1000 / prof.elapsed_time_sec) * 100;
      s += `% of nrt time = ${nrt_percent
        .toFixed(1)
        .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
        total_nrt_time[ff[0]]
      ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
        prof.elapsed_time_sec * 1e3
      ).padWithNonBreakingSpaces(8)})`;
    }

    if (hasNeuronData && total_nc_time[ff[0]] > 0) {
      s += `<br /><span style="height: 20; width: 100; vertical-align: middle" id="nc_bar${nc_bars.length}"></span>&nbsp;`;
      nc_bars.push(
        makeTotalNeuronBar(total_nc_time[ff[0]], prof.elapsed_time_sec, "NC", "darkorange", {
          height: 20,
          width: 100,
        })
      );
      const nc_percent =
        (total_nc_time[ff[0]] / 1000 / prof.elapsed_time_sec) * 100;
      s += `% of nc time = ${nc_percent
        .toFixed(1)
        .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
        total_nc_time[ff[0]]
      ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
        prof.elapsed_time_sec * 1e3
      ).padWithNonBreakingSpaces(8)})`;
    }

    s += `</font>`;

    s += `<br /><span id="button-${id}" title="Click to show or hide profile." style="cursor: pointer; color: blue;" onClick="toggleDisplay('${id}')">`;
    s += `${triangle}`;
    s += "</span>";
    s += `<code> ${ff[0]}</code>`;
    s += ` <select id="display-mode-${id}" style="font-size: 80%; margin-left: 10px;" onchange="onFileDisplayModeChange('${id}')">`;
    s += `<option value="profiled-functions" selected>profiled functions</option>`;
    s += `<option value="profiled-lines">profiled lines only</option>`;
    s += `<option value="all">all lines</option>`;
    s += `</select>`;
    s += `</p>`;
    s += `<div style="${displayStr}" id="profile-${id}">`;
    s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
    tableID++;
    s += makeTableHeader(ff[0], prof.gpu, prof.gpu_device, prof.memory, {
      functions: false,
    }, hasNeuronData);
    s += "<tbody>";
    // Compute all docstring lines
    const linesArray = ff[1].lines.map((entry) => entry.line);
    const docstringLines = stringLines(linesArray);

    // First pass: identify functions/classes that contain profiled lines
    const profiledFunctions = new Set<string>();
    for (const line of ff[1].lines) {
      const total_time =
        line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;
      const has_memory_results =
        line.n_avg_mb +
        line.n_peak_mb +
        line.memory_samples.length +
        (line.n_usage_fraction >= 0.01 ? 1 : 0);
      const has_gpu_results = line.n_gpu_percent >= 1.0;
      const has_nrt_results =
        (line.nrt_time_ms !== undefined && line.nrt_time_ms > 0) ||
        (line.nc_time_ms !== undefined && line.nc_time_ms > 0);

      const hasProfileData =
        total_time > 1.0 ||
        has_memory_results ||
        (has_gpu_results && prof.gpu && !hasNeuronData) ||
        has_nrt_results;

      if (hasProfileData && line.start_function_line > 0) {
        const functionKey = `${line.start_function_line},${line.end_function_line}`;
        profiledFunctions.add(functionKey);
      }
    }

    // Print per-line profiles.
    let prevLineno = -1;
    let index = -1;
    for (const l in ff[1].lines) {
      index += 1;
      const line = ff[1].lines[l];

      if (false) {
        // Disabling spacers
        if (line.lineno > prevLineno + 1) {
          s += "<tr>";
          for (let i = 0; i < columns.length; i++) {
            s += "<td></td>";
          }
          s += `<td class="F${escape(
            ff[0]
          )}-blankline" style="line-height: 1px; background-color: lightgray" data-sort="${
            prevLineno + 1
          }">&nbsp;</td>`;
          s += "</tr>";
        }
      }
      prevLineno = line.lineno;
      s += makeProfileLine(
        line,
        docstringLines.has(index),
        ff[0],
        fileIteration,
        prof,
        cpu_bars,
        memory_bars,
        memory_sparklines,
        memory_activity,
        gpu_pies,
        true,
        nrt_bars,
        nc_bars,
        nc_nrt_pies,
        total_nc_time[ff[0]],
        hasNeuronData,
        profiledFunctions
      );
    }
    s += "</tbody>";
    s += "</table>";
    // Print out function summaries.
    if (prof.files[ff[0]].functions.length) {
      s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
      s += makeTableHeader(ff[0], prof.gpu, prof.gpu_device, prof.memory, {
        functions: true,
      }, hasNeuronData);
      s += "<tbody>";
      tableID++;
      for (const l in prof.files[ff[0]].functions) {
        const line = prof.files[ff[0]].functions[l];
        s += makeProfileLine(
          line,
          false,
          ff[0],
          fileIteration,
          prof,
          cpu_bars,
          memory_bars,
          memory_sparklines,
          memory_activity,
          gpu_pies,
          false,
          nrt_bars,
          nc_bars,
          nc_nrt_pies,
          total_nc_time[ff[0]],
          hasNeuronData
        );
      }
      s += "</table>";
    }
    s += "</div>";
    if (fileIteration < files.length) {
      s += "<hr>";
    }
  }
  // Remove any excluded files.
  files = files.filter((x) => !excludedFiles.has(x));
  s += "</div>";
  const p = document.getElementById("profile");
  if (p) {
    p.innerHTML = s;
  }

  // Logic for turning on and off the gray line separators.
  for (const ff of files) {
    const allHeaders = document.getElementsByClassName(
      `F${escape(ff[0])}-nonline`
    );
    for (let i = 0; i < allHeaders.length; i++) {
      allHeaders[i].addEventListener("click", () => {
        const all = document.getElementsByClassName(
          `F${escape(ff[0])}-blankline`
        ) as HTMLCollectionOf<HTMLElement>;
        for (let i = 0; i < all.length; i++) {
          all[i].style.display = "none";
        }
      });
    }
  }

  for (const ff of files) {
    const lineProfileHeader = document.getElementById(`${escape(ff[0])}-lineProfile`);
    if (lineProfileHeader) {
      lineProfileHeader.addEventListener("click", () => {
        const all = document.getElementsByClassName(
          `F${escape(ff[0])}-blankline`
        ) as HTMLCollectionOf<HTMLElement>;
        for (let i = 0; i < all.length; i++) {
          if (all[i].style.display === "none") {
            all[i].style.display = "block";
          }
        }
      });
    }
  }

  for (let i = 0; i < tableID; i++) {
    const tableElement = document.getElementById(`table-${i}`);
    if (tableElement) {
      new Tablesort(tableElement, { ascending: true });
    }
  }
  memory_sparklines.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#memory_sparkline${index}`, p as object, {
          actions: false,
          renderer: "svg",
        });
      })();
    }
  });

  function embedCharts(charts: (unknown | null)[], prefix: string): void {
    charts.forEach((chart, index) => {
      if (chart) {
        (async () => {
          await vegaEmbed(`#${prefix}${index}`, chart as object, { actions: false });
        })();
      }
    });
  }

  embedCharts(cpu_bars, "cpu_bar");
  embedCharts(gpu_pies, "gpu_pie");
  embedCharts(memory_activity, "memory_activity");
  embedCharts(memory_bars, "memory_bar");

  if (hasNeuronData) {
    for (let i = 0; i < nrt_bars.length; i++) {
      if (nrt_bars[i]) {
        (async () => {
          await vegaEmbed(`#nrt_bar${i}`, nrt_bars[i] as object, { actions: false });
        })();
      }
    }
    for (let i = 0; i < nc_bars.length; i++) {
      if (nc_bars[i]) {
        (async () => {
          await vegaEmbed(`#nc_bar${i}`, nc_bars[i] as object, { actions: false });
        })();
      }
    }
  }

  // Apply the default display mode for each file.
  for (const id of allIds) {
    applyFileDisplayMode(id, "profiled-functions");
  }
  if (prof.program) {
    document.title = "Scalene - " + prof.program;
  } else {
    document.title = "Scalene";
  }
}

export function load(profile: Profile): void {
  (async () => {
    await display(profile);
  })();
}

export function loadFetch(): void {
  (async () => {
    const resp = await fetch("profile.json");
    const profile = await resp.json();
    load(profile);
  })();
}

export function loadFile(): void {
  const input = document.getElementById("fileinput") as HTMLInputElement | null;
  if (input && input.files && input.files[0]) {
    const file = input.files[0];
    const fr = new FileReader();
    fr.onload = doSomething;
    fr.readAsText(file);
  }
}

function doSomething(e: ProgressEvent<FileReader>): void {
  const target = e.target;
  if (target && target.result) {
    const lines = target.result as string;
    const profile = JSON.parse(lines);
    load(profile);
  }
}

export function loadDemo(): void {
  load(example_profile);
}

// Map service values to their field IDs
const serviceFieldMap: Record<string, string> = {
  openai: "openai-fields",
  anthropic: "anthropic-fields",
  gemini: "gemini-fields",
  amazon: "amazon-fields",
  local: "local-fields",
  "azure-openai": "azure-openai-fields",
};

// Toggle provider fields based on selected service
export function toggleServiceFields(): void {
  const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
  const service = serviceSelect?.value ?? "openai";
  window.localStorage.setItem("scalene-service-select", service);

  // Hide all provider sections and show the selected one
  Object.entries(serviceFieldMap).forEach(([key, fieldId]) => {
    const field = document.getElementById(fieldId);
    if (field) {
      field.classList.toggle("active", key === service);
    }
  });
}

// Toggle password visibility
export function togglePassword(button: HTMLButtonElement): void {
  const input = button.previousElementSibling as HTMLInputElement | null;
  if (input) {
    if (input.type === "password") {
      input.type = "text";
      button.textContent = "Hide";
    } else {
      input.type = "password";
      button.textContent = "Show";
    }
  }
}

// Toggle advanced options visibility
export function toggleAdvanced(toggle: HTMLElement): void {
  const advancedOptions = toggle.nextElementSibling as HTMLElement | null;
  if (advancedOptions) {
    const isShown = advancedOptions.classList.toggle("show");
    toggle.innerHTML = (isShown ? "&#9660;" : "&#9654;") + " Advanced options";
  }
}

// Helper to populate a select element with model options
function populateModelSelect(
  selectId: string,
  models: string[],
  currentValue?: string
): void {
  const select = document.getElementById(selectId) as HTMLSelectElement | null;
  if (!select || models.length === 0) return;

  // Save current selection
  const savedValue = currentValue || select.value;

  // Clear existing options
  select.innerHTML = "";

  // Add new options
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    select.appendChild(option);
  });

  // Restore selection if it exists in the new list
  if (models.includes(savedValue)) {
    select.value = savedValue;
  }
}

// Refresh OpenAI models from API
export async function refreshOpenAIModels(): Promise<void> {
  const apiKeyElement = document.getElementById("api-key") as HTMLInputElement | null;
  const apiKey = apiKeyElement?.value ?? "";

  if (!apiKey) {
    alert("Please enter an OpenAI API key first.");
    return;
  }

  // Find the refresh button and show loading state
  const buttons = document.querySelectorAll("#openai-fields .btn-refresh");
  buttons.forEach((btn) => {
    btn.classList.add("loading");
    (btn as HTMLButtonElement).disabled = true;
    btn.textContent = "...";
  });

  try {
    const models = await fetchOpenAIModels(apiKey);
    if (models.length > 0) {
      populateModelSelect("language-model-openai", models);
    } else {
      console.log("No models returned, keeping defaults");
    }
  } catch (error) {
    console.error("Failed to fetch OpenAI models:", error);
  } finally {
    buttons.forEach((btn) => {
      btn.classList.remove("loading");
      (btn as HTMLButtonElement).disabled = false;
      btn.innerHTML = "&#8635;";
    });
  }
}

// Refresh Gemini models from API
export async function refreshGeminiModels(): Promise<void> {
  const apiKeyElement = document.getElementById("gemini-api-key") as HTMLInputElement | null;
  const apiKey = apiKeyElement?.value ?? "";

  if (!apiKey) {
    alert("Please enter a Gemini API key first.");
    return;
  }

  // Find the refresh button and show loading state
  const buttons = document.querySelectorAll("#gemini-fields .btn-refresh");
  buttons.forEach((btn) => {
    btn.classList.add("loading");
    (btn as HTMLButtonElement).disabled = true;
    btn.textContent = "...";
  });

  try {
    const models = await fetchGeminiModels(apiKey);
    if (models.length > 0) {
      populateModelSelect("language-model-gemini", models);
    } else {
      console.log("No models returned, keeping defaults");
    }
  } catch (error) {
    console.error("Failed to fetch Gemini models:", error);
  } finally {
    buttons.forEach((btn) => {
      btn.classList.remove("loading");
      (btn as HTMLButtonElement).disabled = false;
      btn.innerHTML = "&#8635;";
    });
  }
}

function revealInstallMessage(): void {
  const installMsg = document.getElementById("install-models-message");
  const localModelsList = document.getElementById("local-models-list");
  if (installMsg) {
    installMsg.style.display = "block";
  }
  if (localModelsList) {
    localModelsList.style.display = "none";
  }
}

function createSelectElement(modelNames: string[]): HTMLSelectElement {
  const select = document.createElement("select");
  select.style.fontSize = "0.8rem";
  select.id = "language-model-local";
  select.classList.add("persistent");
  select.name = "language-model-local-label";

  modelNames.forEach((modelName) => {
    const option = document.createElement("option");
    option.value = modelName;
    option.textContent = modelName;
    option.id = modelName;
    select.appendChild(option);
  });

  return select;
}

function replaceDivWithSelect(): void {
  const localIpElement = document.getElementById("local-ip") as HTMLInputElement | null;
  const localPortElement = document.getElementById("local-port") as HTMLInputElement | null;
  const local_ip = localIpElement?.value ?? "127.0.0.1";
  const local_port = localPortElement?.value ?? "11434";

  fetchModelNames(local_ip, local_port, revealInstallMessage).then(
    (modelNames) => {
      const selectElement = createSelectElement(modelNames);

      const div = document.getElementById("language-local-models");
      if (div) {
        div.innerHTML = "";
        div.appendChild(selectElement);
      } else {
        console.error('Div with ID "language-local-models" not found.');
      }
    }
  );
}

// Call the function to replace the div with the select element
replaceDivWithSelect();

// Declare envApiKeys as a global variable that may be injected by the template
declare const envApiKeys: {
  openai?: string;
  anthropic?: string;
  gemini?: string;
  azure?: string;
  azureUrl?: string;
  awsAccessKey?: string;
  awsSecretKey?: string;
  awsRegion?: string;
} | undefined;

// Get the first provider option from the select element
function getFirstProvider(): string {
  const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
  return serviceSelect?.options[0]?.value ?? "amazon";
}

// Determine default provider based on environment variables (alphabetical order)
function getDefaultProvider(): string {
  const firstProvider = getFirstProvider();
  if (typeof envApiKeys === "undefined") {
    return firstProvider;
  }
  // Check providers in alphabetical order
  if (envApiKeys.awsAccessKey && envApiKeys.awsSecretKey) return "amazon";
  if (envApiKeys.anthropic) return "anthropic";
  if (envApiKeys.azure) return "azure-openai";
  if (envApiKeys.gemini) return "gemini";
  if (envApiKeys.openai) return "openai";
  return firstProvider;
}

// Set default provider before persistence restores (so localStorage takes precedence)
function initializeDefaultProvider(): void {
  const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
  if (serviceSelect) {
    // Only set default if localStorage doesn't have a saved value
    const savedService = localStorage.getItem("service-select");
    if (!savedService) {
      serviceSelect.value = getDefaultProvider();
    }
    toggleServiceFields();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initializeDefaultProvider();
  processPersistentElements();
});

observeDOM();

// We periodically send a heartbeat to the server to keep it alive.
function sendHeartbeat(): void {
  const xhr = new XMLHttpRequest();
  xhr.open("GET", "/heartbeat", true);
  xhr.send();
}

window.addEventListener("load", () => {
  load(profile);
});

setInterval(sendHeartbeat, 10000); // Send heartbeat every 10 seconds

// Expose functions globally for HTML onclick handlers
(window as unknown as Record<string, unknown>).vsNavigate = vsNavigate;
(window as unknown as Record<string, unknown>).proposeOptimizationRegion = proposeOptimizationRegion;
(window as unknown as Record<string, unknown>).proposeOptimizationLine = proposeOptimizationLine;
(window as unknown as Record<string, unknown>).collapseAll = collapseAll;
(window as unknown as Record<string, unknown>).expandAll = expandAll;
(window as unknown as Record<string, unknown>).toggleDisplay = toggleDisplay;
(window as unknown as Record<string, unknown>).toggleReduced = toggleReduced;
(window as unknown as Record<string, unknown>).onFileDisplayModeChange = onFileDisplayModeChange;
(window as unknown as Record<string, unknown>).load = load;
(window as unknown as Record<string, unknown>).loadFetch = loadFetch;
(window as unknown as Record<string, unknown>).loadFile = loadFile;
(window as unknown as Record<string, unknown>).loadDemo = loadDemo;
(window as unknown as Record<string, unknown>).toggleServiceFields = toggleServiceFields;
(window as unknown as Record<string, unknown>).togglePassword = togglePassword;
(window as unknown as Record<string, unknown>).toggleAdvanced = toggleAdvanced;
(window as unknown as Record<string, unknown>).refreshOpenAIModels = refreshOpenAIModels;
(window as unknown as Record<string, unknown>).refreshGeminiModels = refreshGeminiModels;
