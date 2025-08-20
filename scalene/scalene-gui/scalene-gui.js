import { Buffer } from "buffer";
window.Buffer = Buffer;
import vegaEmbed from 'vega-embed';

import { Prism } from "./prism";
import Tablesort from "./tablesort";
import { proposeOptimization } from "./optimizations";
import { unescapeUnicode, memory_consumed_str, time_consumed_str } from "./utils";
import { makeBar, makeGPUPie, makeMemoryPie, makeMemoryBar, makeSparkline, makeNRTBar, makeNCTimeBar, makeNCNRTPie, makeTotalNeuronBar,
	 Lightning, Explosion, RightTriangle, DownTriangle, WhiteLightning, WhiteExplosion} from "./gui-elements";
import { checkApiKey } from "./openai";
import { fetchModelNames } from "./ollama";
import { observeDOM, processPersistentElements } from "./persistence";

window.checkApiKey = checkApiKey;

export function vsNavigate(filename, lineno) {
  // If we are in VS Code, clicking on a line number in Scalene's web UI will navigate to that line in the source code.
  try {
    const vscode = acquireVsCodeApi();
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

let showedExplosion = {}; // Used so we only show one explosion per region.

export function proposeOptimizationRegion(filename, file_number, line) {
  proposeOptimization(
    filename,
    file_number,
    JSON.parse(decodeURIComponent(line)),
    { regions: true },
  );
}

export function proposeOptimizationLine(filename, file_number, line) {
  proposeOptimization(
    filename,
    file_number,
    JSON.parse(decodeURIComponent(line)),
    { regions: false },
  );
}

const CPUColor = "blue";
const MemoryColor = "green";
const CopyColor = "goldenrod";
let columns = [];

function stringLines(lines) {
    const docstringLines = new Set();

    let inDocstring = false;      // Are we currently inside a docstring?
    let docstringDelimiter = null; // Either `'''` or `"""` when in a docstring.

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        let searchIndex = 0;
        // We'll record if we were already in a docstring at the start of this line.
        let wasInDocstring = inDocstring;

        // Repeatedly look for triple quotes in the current line.
        while (true) {
            // Find the next occurrence of either `'''` or `"""`.
            const nextTripleSingle = line.indexOf("'''", searchIndex);
            const nextTripleDouble = line.indexOf('"""', searchIndex);

            // Figure out which one occurs first (if either).
            let nextIndex = -1;
            let foundDelimiter = null;

            if (nextTripleSingle !== -1 && (nextTripleDouble === -1 || nextTripleSingle < nextTripleDouble)) {
                nextIndex = nextTripleSingle;
                foundDelimiter = "'''";
            } else if (nextTripleDouble !== -1 && (nextTripleSingle === -1 || nextTripleDouble < nextTripleSingle)) {
                nextIndex = nextTripleDouble;
                foundDelimiter = '"""';
            }

            // If no further triple quotes found in this line, break out of the loop.
            if (nextIndex === -1) {
                break;
            }

            // Advance searchIndex so that subsequent searches move past this point.
            searchIndex = nextIndex + 3;

            // Toggle logic if we've found a triple quote.
            if (!inDocstring) {
                // Not in a docstring, so this starts one.
                inDocstring = true;
                docstringDelimiter = foundDelimiter;
            } else {
                // Already in a docstring, check if it matches our current delimiter.
                if (docstringDelimiter === foundDelimiter) {
                    // This ends our current docstring.
                    inDocstring = false;
                    docstringDelimiter = null;
                }
            }
        }

        // If we were in a docstring at any point during this line, mark it.
        // (If wasInDocstring was true at the start or inDocstring is true now,
        //  it means this line is part of a docstring.)
        if (wasInDocstring || inDocstring) {
            docstringLines.add(i);
        }
    }
    return docstringLines;
}

function makeTableHeader(fname, gpu, gpu_device, memory, params, hasNeuronData) {
  let tableTitle;
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
  // Only add NRT/NC columns if neuron data exists in the profile
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
      fname,
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
  let id;
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

function hideEmptyProfiles() {
  const elts = document.getElementsByClassName("empty-profile");
  for (const elt of elts) {
    const s = elt.style;
    s.display = "none";
  }
}

export function toggleReduced() {
  const elts = document.getElementsByClassName("empty-profile");
  for (const elt of elts) {
    const s = elt.style;
    if (s.display == "") {
      s.display = "none";
    } else {
      s.display = "";
    }
  }
}

function makeProfileLine(
  line,
  inDocstring,
  filename,
  file_number,
  prof,
  cpu_bars,
  memory_bars,
  memory_sparklines,
  memory_activity,
  gpu_pies,
  propose_optimizations,
  nrt_bars,
  nc_bars,
  nc_nrt_pies,
  total_nc_time_for_file,
  hasNeuronData,
) {
  let total_time =
    line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;
  let total_region_time = 0;
  let region_has_memory_results = 0;
  let region_has_gpu_results = 0;
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
      (currline.n_usage_fraction >= 0.01);
    region_has_gpu_results |= line.n_gpu_percent >= 1.0;
  }
  // Disable optimization proposals for low CPU runtime lines.

  // TODO: tailor prompt for memory optimization when that's the only inefficiency.
  // ALSO propose optimizations not just for execution time but also for memory usage.
  if (propose_optimizations) {
    if (total_time < 1.0 && line.start_region_line === line.end_region_line) {
      propose_optimizations = false;
    }
    if (line.start_region_line != line.end_region_line) {
      if (total_region_time < 1.0) {
        propose_optimizations = false;
      }
    }
  }
  const has_memory_results =
    line.n_avg_mb +
    line.n_peak_mb +
    line.memory_samples.length +
    (line.n_usage_fraction >= 0.01);
  const has_gpu_results = line.n_gpu_percent >= 1.0;
  const has_nrt_results = (line.nrt_percent !== undefined && line.nrt_percent !== null && line.nrt_percent > 0);
  const start_region_line = line.start_region_line;
  const end_region_line = line.end_region_line;
  // Only show the explosion (optimizing a whole region) once.
  let explosionString;
  let showExplosion;
  if (
    start_region_line === end_region_line ||
    [[start_region_line - 1, end_region_line]] in showedExplosion
  ) {
    explosionString = WhiteExplosion;
    showExplosion = false;
  } else {
    explosionString = Explosion;
    if (start_region_line && end_region_line) {
      showedExplosion[[start_region_line - 1, end_region_line]] = true;
      showExplosion = true;
    }
  }
  // If the region is too big, for some definition of "too big", don't show it.
  showExplosion &= end_region_line - start_region_line <= maxLinesPerRegion;

  let s = "";
  if (
    total_time > 1.0 ||
    has_memory_results ||
    has_gpu_results ||
    has_nrt_results ||
    (showExplosion &&
      start_region_line != end_region_line &&
      (total_region_time >= 1.0 ||
        region_has_memory_results ||
        region_has_gpu_results))
  ) {
    s += "<tr>";
  } else {
    s += "<tr class='empty-profile'>";
  }
  const total_time_str = String(total_time.toFixed(1)).padStart(10, " ");
  s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${total_time_str}'>`;
  s += `<span style="height: 20; width: 100; vertical-align: middle" id="cpu_bar${cpu_bars.length}"></span>`;
  if (total_time) {
    cpu_bars.push(
      makeBar(
        line.n_cpu_percent_python,
        line.n_cpu_percent_c,
        line.n_sys_percent,
        { height: 20, width: 100 },
      ),
    );
  } else {
    cpu_bars.push(null);
  }
  if (prof.memory) {
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_peak_mb.toFixed(0),
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    if (line.n_peak_mb) {
      memory_bars.push(
        makeMemoryBar(
          line.n_peak_mb.toFixed(0),
          "peak memory",
          parseFloat(line.n_python_fraction),
          prof.max_footprint_mb.toFixed(2),
          "darkgreen",
          { height: 20, width: 100 },
        ),
      );
    } else {
      memory_bars.push(null);
    }
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_avg_mb.toFixed(0),
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    s += "</td>";
    if (line.n_avg_mb) {
      memory_bars.push(
        makeMemoryBar(
          line.n_avg_mb.toFixed(0),
          "average memory",
          parseFloat(line.n_python_fraction),
          prof.max_footprint_mb.toFixed(2),
          "darkgreen",
          { height: 20, width: 100 },
        ),
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
        if (line.lineno in prof.files[filename].leaks) {
          leak_velocity = prof.files[filename].leaks[line.lineno].velocity_mb_s;
        }
      }
      memory_sparklines.push(
        makeSparkline(
          line.memory_samples,
          prof.elapsed_time_sec * 1e9,
          prof.max_footprint_mb,
          leak_velocity,
          { height: 20, width: 75 },
        ),
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
            (1 - parseFloat(line.n_python_fraction)),
          100 * line.n_usage_fraction * parseFloat(line.n_python_fraction),
          { width: 30 },
        ),
      );
    } else {
      memory_activity.push(null);
    }
    //      s += `<font style="font-size: small">${String(
    //        (100 * line.n_usage_fraction).toFixed(0)
    //      ).padStart(10, " ")}%&nbsp;&nbsp;&nbsp;</font>`;
    s += "</td>";
    if (line.n_copy_mb_s < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${line.n_copy_mb_s.toFixed(
        0,
      )}&nbsp;&nbsp;&nbsp;</font></td>`;
    }
  }
  if (prof.gpu && !hasNeuronData) {
    if (line.n_gpu_percent < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      //	    s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${line.n_gpu_percent.toFixed(0)}%</font></td>`;
      s += `<td style="width: 50; vertical-align: middle" align="right" data-sort="${line.n_gpu_percent}">`;
      s += `<span style="height: 20; width: 30; vertical-align: middle" id="gpu_pie${gpu_pies.length}"></span>`;
      s += "</td>";
      gpu_pies.push(
        makeGPUPie(line.n_gpu_percent, prof.gpu_device, {
          height: 20,
          width: 30,
        }),
      );
      // gpu_pies.push(makeGPUBar(line.n_gpu_percent, prof.gpu_device, { height: 20, width: 100 }));
    }
    if (true) {
      if (line.n_gpu_peak_memory_mb < 1.0 || line.n_gpu_percent < 1.0) {
        s += '<td style="width: 100"></td>';
      } else {
        let mem = line.n_gpu_peak_memory_mb;
        let memStr = "MB";
        if (mem >= 1024) {
          mem /= 1024;
          memStr = "GB";
        }
        s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${mem.toFixed(0)}${memStr}&nbsp;&nbsp;</font></td>`;
      }
    }
  }
  
  // Add neuron columns only if the profile contains neuron data 
  if (hasNeuronData) {
    // Add NRT columns
    // NRT time bar
    if ((line.nrt_time_ms !== undefined && line.nrt_time_ms > 0) || (line.nrt_percent !== undefined && line.nrt_percent > 0)) {
      const sortValue = line.nrt_time_ms || line.nrt_percent || 0;
      s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${sortValue.toFixed(1)}'>`;
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nrt_bar${nrt_bars.length}"></span>`;
      s += "</td>";
      nrt_bars.push(
        makeNRTBar(
          line.nrt_time_ms || 0,
          prof.elapsed_time_sec,
          { height: 20, width: 100 },
        ),
      );
    } else {
      s += '<td style="width: 100"></td>';
      nrt_bars.push(null);
    }
    
    // Add NC time bar column
    if (line.nc_time_ms !== undefined && line.nc_time_ms > 0) {
      s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${line.nc_time_ms.toFixed(1)}'>`;
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nc_bar${nc_bars.length}"></span>`;
      s += "</td>";
      nc_bars.push(
        makeNCTimeBar(
          line.nc_time_ms,
          prof.elapsed_time_sec,
          { height: 20, width: 100 },
        ),
      );
    } else {
      s += '<td style="width: 100"></td>';
      nc_bars.push(null);
    }
  }
  
  const empty_profile =
    total_time ||
    has_memory_results ||
    has_gpu_results ||
    has_nrt_results ||
    end_region_line != start_region_line
      ? ""
      : "empty-profile";
  s += `<td align="right" class="dummy ${empty_profile}" style="vertical-align: middle; width: 50" data-sort="${
    line.lineno
  }"><span onclick="vsNavigate('${escape(filename)}',${
    line.lineno
  })"><font color="gray" style="font-size: 70%; vertical-align: middle" >${
    line.lineno
  }&nbsp;</font></span></td>`;

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
  let newLine = structuredClone(line);
  // TODO: verify that this isn't double counting anything
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
      // TODO:
      // GPU memory
      newLine.n_core_utilization +=
        (currline.n_cpu_percent_python + currline.n_cpu_percent_c) *
        currline.n_core_utilization; // weigh by percentage
    }
    newLine.n_copy_mb_s = mb_copied / prof.elapsed_time_sec;
    s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for the entire region starting here." onclick="proposeOptimizationRegion('${escape(
      filename,
    )}', ${file_number}, '${encodeURIComponent(JSON.stringify(newLine))}'); event.preventDefault()">${regionOptimizationString}</span>`;
  } else {
    s += regionOptimizationString;
  }

  const lineOptimizationString = propose_optimizations
    ? `${Lightning}`
    : `${WhiteLightning}`;
  if (propose_optimizations) {
    s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for this line." onclick="proposeOptimizationLine('${escape(filename)}', ${file_number}, '${encodeURIComponent(JSON.stringify(line))}'); event.preventDefault()">${lineOptimizationString}</span>`;
    // s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for this line." onclick="proposeOptimizationLine('${escape(filename,)}', ${file_number}, ${JSON.stringify(line)}); event.preventDefault()">${lineOptimizationString}</span>`;
  } else {
    s += lineOptimizationString;
  }
  s += `<pre style="height: 10; display: inline; white-space: pre-wrap; overflow-x: auto; border: 0px; vertical-align: middle"><code class="language-python ${optionalInDocstring} ${empty_profile}">${codeLine}<span id="code-${file_number}-${line.lineno}" bgcolor="white"></span></code></pre></td>`;
  s += "</tr>";
  return s;
}

// Track all profile ids so we can collapse and expand them en masse.
let allIds = [];

export function collapseAll() {
  for (const id of allIds) {
    collapseDisplay(id);
  }
}

export function expandAll() {
  for (const id of allIds) {
    expandDisplay(id);
  }
}

function collapseDisplay(id) {
  const d = document.getElementById(`profile-${id}`);
  d.style.display = "none";
  document.getElementById(`button-${id}`).innerHTML = RightTriangle;
}

function expandDisplay(id) {
  const d = document.getElementById(`profile-${id}`);
  d.style.display = "block";
  document.getElementById(`button-${id}`).innerHTML = DownTriangle;
}

export function toggleDisplay(id) {
  const d = document.getElementById(`profile-${id}`);
  if (d.style.display == "block") {
    d.style.display = "none";
    document.getElementById(`button-${id}`).innerHTML = RightTriangle;
  } else {
    d.style.display = "block";
    document.getElementById(`button-${id}`).innerHTML = DownTriangle;
  }
}

String.prototype.padWithNonBreakingSpaces = function (targetLength) {
  let nbsp = "&nbsp;";
  let padding = "";
  let currentLength = this.length * nbsp.length;
  targetLength *= nbsp.length;

  while (currentLength < targetLength) {
    padding += nbsp;
    currentLength += nbsp.length;
  }

  return padding + this;
};

async function display(prof) {
  //    console.log(JSON.stringify(prof.stacks));
  // Clear explosions.
  showedExplosion = {};
  
  // Compute overall usage and detect neuron data FIRST
  let cpu_python = 0;
  let cpu_native = 0;
  let cpu_system = 0;
  let mem_python = 0;
  let max_alloc = 0;
  let cp = {};
  let cn = {};
  let cs = {};
  let mp = {};
  let ma = {};
  let total_nc_time = {}; // Total NC time per file
  let total_nrt_time = {}; // Total NRT time per file
  let hasNeuronData = false; // Check if any neuron profiling data exists
  let overall_nc_time = 0; // Total NC time across all files
  let overall_nrt_time = 0; // Total NRT time across all files
  
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
      // Calculate total NC time for this file and detect neuron data
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
    overall_nc_time += total_nc_time[f];
    overall_nrt_time += total_nrt_time[f];
  }

  // Restore the API key from local storage (if any).
  let old_key = "";
  old_key = window.localStorage.getItem("scalene-api-key");

  if (old_key) {
    document.getElementById("api-key").value = old_key;
    // Update the status.
    checkApiKey(old_key);
  }

  let selectedService = window.localStorage.getItem("scalene-service-select");
  if (selectedService) {
    document.getElementById("service-select").value = selectedService;
    toggleServiceFields();
  }

  const gpu_checkbox = document.getElementById("use-gpu-checkbox") || "";
  // Set the GPU checkbox on if the profile indicated the presence of a GPU.
  if (gpu_checkbox.checked != prof.gpu) {
    gpu_checkbox.click();
  }
  if (prof.gpu) {
    document.getElementById("accelerator-name").innerHTML = prof.gpu_device;
  }
  globalThis.profile = prof;
  let memory_sparklines = [];
  let memory_activity = [];
  let gpu_pies = [];
  let memory_bars = [];
  let nrt_bars = [];
  let nc_bars = [];
  let nc_nrt_pies = [];
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
      prof.max_footprint_mb,
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
        { height: 20, width: 200 },
      ),
    );
  }
  s += "</tr>";

  let cpu_bars = [];
  cpu_bars.push(
    makeBar(cpu_python, cpu_native, cpu_system, { height: 20, width: 200 }),
  );
  if (prof.memory) {
    memory_bars.push(
      makeMemoryBar(
        prof.max_footprint_mb.toFixed(2),
        "memory",
        mem_python / max_alloc,
        prof.max_footprint_mb.toFixed(2),
        "darkgreen",
        { height: 20, width: 150 },
      ),
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
    p.innerHTML = s;
    return;
  }

  s +=
    '<br class="text-left"><span style="font-size: 80%; color: blue; cursor : pointer;" onClick="expandAll()">&nbsp;show all</span> | <span style="font-size: 80%; color: blue; cursor : pointer;" onClick="collapseAll()">hide all</span>';
  s += ` | <span style="font-size: 80%; color: blue" onClick="document.getElementById('reduce-checkbox').click()">only display profiled lines&nbsp;</span><input type="checkbox" id="reduce-checkbox" checked onClick="toggleReduced()" /></br>`;
  
  s += '<div class="container-fluid">';

  // Convert files to an array and sort it in descending order by percent of CPU time.
  let files = Object.entries(prof.files);
  files.sort((x, y) => {
    return y[1].percent_cpu_time - x[1].percent_cpu_time;
  });

  // Print profile for each file
  let fileIteration = 0;
  allIds = [];
  let excludedFiles = new Set();
  for (const ff of files) {
    fileIteration++;
    // Stop once total CPU time / memory consumption are below some threshold (1%)
    // NOTE: need to incorporate GPU time here as well. FIXME.
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
      makeBar(cp[ff[0]], cn[ff[0]], cs[ff[0]], { height: 20, width: 100 }),
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
          { height: 20, width: 100 },
        ),
      );
    }
    s += `<font style="font-size: 90%">% of time = ${ff[1].percent_cpu_time
      .toFixed(1)
      .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
      (ff[1].percent_cpu_time / 100.0) * prof.elapsed_time_sec * 1e3,
    ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
      prof.elapsed_time_sec * 1e3,
    ).padWithNonBreakingSpaces(8)})<br />`;
    
    // Add neuron bars in the same format as CPU bars if neuron data exists
    if (hasNeuronData && total_nrt_time[ff[0]] > 0) {
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nrt_bar${nrt_bars.length}"></span>&nbsp;`;
      nrt_bars.push(
        makeTotalNeuronBar(
          total_nrt_time[ff[0]],
          prof.elapsed_time_sec,
          "NRT",
          "purple",
          { height: 20, width: 100 },
        ),
      );
      const nrt_percent = (total_nrt_time[ff[0]] / 1000 / prof.elapsed_time_sec) * 100;
      s += `<font style="font-size: 90%">% of nrt time = ${nrt_percent
        .toFixed(1)
        .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
        total_nrt_time[ff[0]],
      ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
        prof.elapsed_time_sec * 1e3,
      ).padWithNonBreakingSpaces(8)})<br />`;
    }
    
    if (hasNeuronData && total_nc_time[ff[0]] > 0) {
      s += `<span style="height: 20; width: 100; vertical-align: middle" id="nc_bar${nc_bars.length}"></span>&nbsp;`;
      nc_bars.push(
        makeTotalNeuronBar(
          total_nc_time[ff[0]],
          prof.elapsed_time_sec,
          "NC",
          "darkorange",
          { height: 20, width: 100 },
        ),
      );
      const nc_percent = (total_nc_time[ff[0]] / 1000 / prof.elapsed_time_sec) * 100;
      s += `<font style="font-size: 90%">% of nc time = ${nc_percent
        .toFixed(1)
        .padWithNonBreakingSpaces(5)}% (${time_consumed_str(
        total_nc_time[ff[0]],
      ).padWithNonBreakingSpaces(8)} / ${time_consumed_str(
        prof.elapsed_time_sec * 1e3,
      ).padWithNonBreakingSpaces(8)})<br />`;
    }
    s += `<span id="button-${id}" title="Click to show or hide profile." style="cursor: pointer; color: blue;" onClick="toggleDisplay('${id}')">`;
    s += `${triangle}`;
    s += "</span>";
    s += `<code> ${ff[0]}</code>`;
    s += `</font></p>`;
    s += `<div style="${displayStr}" id="profile-${id}">`;
    s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
    tableID++;
    s += makeTableHeader(ff[0], prof.gpu, prof.gpu_device, prof.memory, {
      functions: false,
    }, hasNeuronData);
    s += "<tbody>";
    // Compute all docstring lines
    const linesArray = ff[1].lines.map(entry => entry.line);
    const docstringLines = stringLines(linesArray);
    // Print per-line profiles.
    let prevLineno = -1;
    let index = -1;
    for (const l in ff[1].lines) {
      index += 1;
      const line = ff[1].lines[l];

      if (false) {
        // Disabling spacers
        // Add a space whenever we skip a line.
        if (line.lineno > prevLineno + 1) {
          s += "<tr>";
          for (let i = 0; i < columns.length; i++) {
            s += "<td></td>";
          }
          s += `<td class="F${escape(
            ff[0],
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
          false, // functions are not docstrings
          ff[0],
          fileIteration,
          prof,
          cpu_bars,
          memory_bars,
          memory_sparklines,
          memory_activity,
          gpu_pies,
          false, // no optimizations here
          nrt_bars,
          nc_bars,
          nc_nrt_pies,
          total_nc_time[ff[0]],
          hasNeuronData,
        );
      }
      s += "</table>";
    }
    s += "</div>";
    //    fileIteration++;
    // Insert empty lines between files.
    if (fileIteration < files.length) {
      s += "<hr>";
    }
  }
  // Remove any excluded files.
  files = files.filter((x) => !excludedFiles.has(x));
  s += "</div>";
  const p = document.getElementById("profile");
  p.innerHTML = s;

  // Logic for turning on and off the gray line separators.

  // If you click on any header to sort (except line profiles), turn gray lines off.
  for (const ff of files) {
    const allHeaders = document.getElementsByClassName(
      `F${escape(ff[0])}-nonline`,
    );
    for (let i = 0; i < allHeaders.length; i++) {
      allHeaders[i].addEventListener("click", () => {
        const all = document.getElementsByClassName(
          `F${escape(ff[0])}-blankline`,
        );
        for (let i = 0; i < all.length; i++) {
          all[i].style.display = "none";
        }
      });
    }
  }

  // If you click on the line profile header, and gray lines are off, turn them back on.
  for (const ff of files) {
    document
      .getElementById(`${escape(ff[0])}-lineProfile`)
      .addEventListener("click", () => {
        const all = document.getElementsByClassName(
          `F${escape(ff[0])}-blankline`,
        );
        for (let i = 0; i < all.length; i++) {
          if (all[i].style.display === "none") {
            all[i].style.display = "block";
          }
        }
      });
  }

  for (let i = 0; i < tableID; i++) {
    new Tablesort(document.getElementById(`table-${i}`), { ascending: true });
  }
  memory_sparklines.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#memory_sparkline${index}`, p, {
          actions: false,
          renderer: "svg",
        });
      })();
    }
  });

  function embedCharts(charts, prefix) {
    charts.forEach((chart, index) => {
      if (chart) {
        (async () => {
          await vegaEmbed(`#${prefix}${index}`, chart, { actions: false });
        })();
      }
    });
  }

  embedCharts(cpu_bars, "cpu_bar");
  embedCharts(gpu_pies, "gpu_pie");
  embedCharts(memory_activity, "memory_activity");
  embedCharts(memory_bars, "memory_bar");
  
  // Embed neuron charts
  if (hasNeuronData) {
    for (let i = 0; i < nrt_bars.length; i++) {
      if (nrt_bars[i]) {
        (async () => {
          await vegaEmbed(`#nrt_bar${i}`, nrt_bars[i], { actions: false });
        })();
      }
    }
    for (let i = 0; i < nc_bars.length; i++) {
      if (nc_bars[i]) {
        (async () => {
          await vegaEmbed(`#nc_bar${i}`, nc_bars[i], { actions: false });
        })();
      }
    }
  }

  // Hide all empty profiles by default.
  hideEmptyProfiles();
  if (prof.program) {
    document.title = "Scalene - " + prof.program;
  } else {
    document.title = "Scalene";
  }
}

export function load(profile) {
  (async () => {
    // let resp = await fetch(jsonFile);
    // let prof = await resp.json();
    await display(profile);
  })();
}

export function loadFetch() {
  (async () => {
    let resp = await fetch("profile.json");
    let profile = await resp.json();
    load(profile);
  })();
}

export function loadFile() {
  const input = document.getElementById("fileinput");
  const file = input.files[0];
  const fr = new FileReader();
  fr.onload = doSomething;
  fr.readAsText(file);
}

function doSomething(e) {
  let lines = e.target.result;
  const profile = JSON.parse(lines);
  load(profile);
}

export function loadDemo() {
  load(example_profile);
}

// JavaScript function to toggle fields based on selected service
export function toggleServiceFields() {
  let service = document.getElementById("service-select").value;
  window.localStorage.setItem("scalene-service-select", service);
  document.getElementById("openai-fields").style.display =
    service === "openai" ? "block" : "none";
  document.getElementById("amazon-fields").style.display =
    service === "amazon" ? "block" : "none";
  document.getElementById("local-fields").style.display =
    service === "local" ? "block" : "none";
  document.getElementById("azure-openai-fields").style.display =
    service === "azure-openai" ? "block" : "none";
}

function revealInstallMessage() {
  document.getElementById("install-models-message").style.display = "block";
  document.getElementById("local-models-list").style.display = "none";
}


function createSelectElement(modelNames) {
  // Create the select element
  const select = document.createElement("select");
  select.style.fontSize = "0.8rem";
  select.id = "language-model-local";
  select.classList.add("persistent");
  select.name = "language-model-local-label";

  // Add options to the select element
  modelNames.forEach((modelName) => {
    const option = document.createElement("option");
    option.value = modelName;
    option.textContent = modelName;
    option.id = modelName;
    select.appendChild(option);
  });

  return select;
}

function replaceDivWithSelect() {
    const local_ip = document.getElementById("local-ip").value;
    const local_port = document.getElementById("local-port").value;
    fetchModelNames(local_ip, local_port, revealInstallMessage).then((modelNames) => {
    // Create the select element with options
    const selectElement = createSelectElement(modelNames);

    // Find the div and replace its content with the select element
    const div = document.getElementById("language-local-models");
    if (div) {
      div.innerHTML = ""; // Clear existing content
      div.appendChild(selectElement);
    } else {
      console.error('Div with ID "language-local-models" not found.');
    }
    //    atLeastOneModel = true;
  });
}

// Call the function to replace the div with the select element
replaceDivWithSelect();


document.addEventListener("DOMContentLoaded", () => {
  processPersistentElements();
});

observeDOM();

// We periodically send a heartbeat to the server to keep it alive.
// The server shuts down if it hasn't received a heartbeat in a sufficiently long interval;
// This handles both the case when the browser tab is closed and when the browser is shut down.
function sendHeartbeat() {
  let xhr = new XMLHttpRequest();
  xhr.open("GET", "/heartbeat", true);
  xhr.send();
}

window.addEventListener("load", () => {
  load(profile);
});

setInterval(sendHeartbeat, 10000); // Send heartbeat every 10 seconds
