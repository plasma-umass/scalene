import { Buffer } from "buffer";
window.Buffer = Buffer;
import vegaEmbed from 'vega-embed';

import { Prism } from "./prism";
import Tablesort from "./tablesort";
import { optimizeCode } from "./optimizations";
import { memory_consumed_str, time_consumed_str } from "./utils";
import { makeBar, makeGPUPie, makeMemoryPie, makeMemoryBar, makeSparkline } from "./gui-elements";

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

const RightTriangle = "&#9658"; // right-facing triangle symbol (collapsed view)
const DownTriangle = "&#9660"; // downward-facing triangle symbol (expanded view)
const Lightning = "&#9889;"; // lightning bolt (for optimizing a line)
const Explosion = "&#128165;"; // explosion (for optimizing a region)
const WhiteLightning = `<span style="opacity:0">${Lightning}</span>`; // invisible but same width as lightning bolt
const WhiteExplosion = `<span style="opacity:0">${Explosion}</span>`; // invisible but same width as lightning bolt
const maxLinesPerRegion = 50; // Only show regions that are no more than this many lines.

let showedExplosion = {}; // Used so we only show one explosion per region.

function unescapeUnicode(s) {
  return s.replace(/\\u([\dA-F]{4})/gi, function (match, p1) {
    return String.fromCharCode(parseInt(p1, 16));
  });
}

async function tryApi(apiKey) {
  const response = await fetch("https://api.openai.com/v1/completions", {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
  });
  return response;
}

async function isValidApiKey(apiKey) {
  const response = await tryApi(apiKey);
  const data = await response.json();
  if (
    data.error &&
    data.error.code in
      {
        invalid_api_key: true,
        invalid_request_error: true,
        model_not_found: true,
        insufficient_quota: true,
      }
  ) {
    return false;
  } else {
    return true;
  }
}

function checkApiKey(apiKey) {
  (async () => {
    try {
      window.localStorage.setItem("scalene-api-key", apiKey);
    } catch {
      // Do nothing if key not found
    }
    // If the API key is empty, clear the status indicator.
    if (apiKey.length === 0) {
      document.getElementById("valid-api-key").innerHTML = "";
      return;
    }
    const isValid = await isValidApiKey(apiKey);
    if (!isValid) {
      document.getElementById("valid-api-key").innerHTML = "&#10005;";
    } else {
      document.getElementById("valid-api-key").innerHTML = "&check;";
    }
  })();
}

function countSpaces(str) {
  // Use a regular expression to match any whitespace character at the start of the string
  const match = str.match(/^\s+/);

  // If there was a match, return the length of the match
  if (match) {
    return match[0].length;
  }

  // Otherwise, return 0
  return 0;
}

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

export function proposeOptimization(filename, file_number, line, params) {
  filename = unescape(filename);
  const useRegion = params["regions"];
  const prof = globalThis.profile;
  const this_file = prof.files[filename].lines;
  const imports = prof.files[filename].imports.join("\n");
  const start_region_line = this_file[line.lineno - 1]["start_region_line"];
  const end_region_line = this_file[line.lineno - 1]["end_region_line"];
  let context;
  const code_line = this_file[line.lineno - 1]["line"];
  let code_region;
  if (useRegion) {
    code_region = this_file
      .slice(start_region_line - 1, end_region_line)
      .map((e) => e["line"])
      .join("");
    context = this_file
      .slice(
        Math.max(0, start_region_line - 10),
        Math.min(start_region_line - 1, this_file.length),
      )
      .map((e) => e["line"])
      .join("");
  } else {
    code_region = code_line;
    context = this_file
      .slice(
        Math.max(0, line.lineno - 10),
        Math.min(line.lineno - 1, this_file.length),
      )
      .map((e) => e["line"])
      .join("");
  }
  // Count the number of leading spaces to match indentation level on output
  let leadingSpaceCount = countSpaces(code_line) + 3; // including the lightning bolt and explosion
  let indent =
    WhiteLightning + WhiteExplosion + "&nbsp;".repeat(leadingSpaceCount - 1);
  const elt = document.getElementById(`code-${file_number}-${line.lineno}`);
  (async () => {
    // TODO: check Amazon credentials
    const service = document.getElementById("service-select").value;
    if (service === "openai") {
      const isValid = await isValidApiKey(
        document.getElementById("api-key").value,
      );
      if (!isValid) {
        alert(
          "You must enter a valid OpenAI API key to activate proposed optimizations.",
        );
        document.getElementById("ai-optimization-options").open = true;
        return;
      }
    }
    if (service == "local") {
      if (
        document.getElementById("local-models-list").style.display === "none"
      ) {
        // No service was found.
        alert(
          "You must be connected to a running Ollama server to activate proposed optimizations.",
        );
        document.getElementById("ai-optimization-options").open = true;
        return;
      }
    }
    elt.innerHTML = `<em>${indent}working...</em>`;
    let message = await optimizeCode(imports, code_region, line, context);
    if (!message) {
      elt.innerHTML = "";
      return;
    }
    // Canonicalize newlines
    message = message.replace(/\r?\n/g, "\n");
    // Indent every line and format it
    const formattedCode = message
      .split("\n")
      .map(
        (line) =>
          indent + Prism.highlight(line, Prism.languages.python, "python"),
      )
      .join("<br />");
    // Display the proposed optimization, with click-to-copy functionality.
    elt.innerHTML = `<hr><span title="click to copy" style="cursor: copy" id="opt-${file_number}-${line.lineno}">${formattedCode}</span>`;
    const thisElt = document.getElementById(
      `opt-${file_number}-${line.lineno}`,
    );
    thisElt.addEventListener("click", async (e) => {
      await copyOnClick(e, message);
      // After copying, briefly change the cursor back to the default to provide some visual feedback..
      thisElt.style = "cursor: auto";
      await new Promise((resolve) => setTimeout(resolve, 125));
      thisElt.style = "cursor: copy";
    });
  })();
}

async function copyOnClick(event, message) {
  event.preventDefault();
  event.stopPropagation();
  await navigator.clipboard.writeText(message);
}

const CPUColor = "blue";
const MemoryColor = "green";
const CopyColor = "goldenrod";
let columns = [];

function makeTableHeader(fname, gpu, gpu_device, memory, params) {
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
  if (gpu) {
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
  filename,
  file_number,
  prof,
  cpu_bars,
  memory_bars,
  memory_sparklines,
  memory_activity,
  gpu_pies,
  propose_optimizations,
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
  if (prof.gpu) {
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
  const empty_profile =
    total_time ||
    has_memory_results ||
    has_gpu_results ||
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
  s += `<pre style="height: 10; display: inline; white-space: pre-wrap; overflow-x: auto; border: 0px; vertical-align: middle"><code class="language-python ${empty_profile}">${codeLine}<span id="code-${file_number}-${line.lineno}" bgcolor="white"></span></code></pre></td>`;
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
  let cpu_bars = [];
  let gpu_pies = [];
  let memory_bars = [];
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

  // Compute overall usage.
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
  for (const f in prof.files) {
    cp[f] = 0;
    cn[f] = 0;
    cs[f] = 0;
    mp[f] = 0;
    ma[f] = 0;
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
    }
    cpu_python += cp[f];
    cpu_native += cn[f];
    cpu_system += cs[f];
    mem_python += mp[f];
  }
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
    });
    s += "<tbody>";
    // Print per-line profiles.
    let prevLineno = -1;
    for (const l in ff[1].lines) {
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
        ff[0],
        fileIteration,
        prof,
        cpu_bars,
        memory_bars,
        memory_sparklines,
        memory_activity,
        gpu_pies,
        true,
      );
    }
    s += "</tbody>";
    s += "</table>";
    // Print out function summaries.
    if (prof.files[ff[0]].functions.length) {
      s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
      s += makeTableHeader(ff[0], prof.gpu, prof.gpu_device, prof.memory, {
        functions: true,
      });
      s += "<tbody>";
      tableID++;
      for (const l in prof.files[ff[0]].functions) {
        const line = prof.files[ff[0]].functions[l];
        s += makeProfileLine(
          line,
          ff[0],
          fileIteration,
          prof,
          cpu_bars,
          memory_bars,
          memory_sparklines,
          memory_activity,
          gpu_pies,
          false, // no optimizations here
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

async function fetchModelNames() {
  try {
    const local_ip = document.getElementById("local-ip").value;
    const local_port = document.getElementById("local-port").value;
    const response = await fetch(`http://${local_ip}:${local_port}/api/tags`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();

    // Extracting the model names
    const modelNames = data.models.map((model) => model.name);
    if (modelNames.length === 0) {
      revealInstallMessage();
    }
    return modelNames;
  } catch (error) {
    console.error("Error fetching model names:", error);
    revealInstallMessage();
    return [];
  }
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
  fetchModelNames().then((modelNames) => {
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

function restoreState(el) {
  const savedValue = localStorage.getItem(el.id);

  if (savedValue !== null) {
    switch (el.type) {
      case "checkbox":
      case "radio":
        el.checked = savedValue === "true";
        break;
      default:
        el.value = savedValue;
        break;
    }
  }
}

function saveState(el) {
  el.addEventListener("change", () => {
    switch (el.type) {
      case "checkbox":
      case "radio":
        localStorage.setItem(el.id, el.checked);
        break;
      default:
        localStorage.setItem(el.id, el.value);
        break;
    }
  });
}

// Process all DOM elements in the class 'persistent', which saves their state in localStorage and restores them on load.
function processPersistentElements() {
  const persistentElements = document.querySelectorAll(".persistent");

  // Restore state
  persistentElements.forEach((el) => {
    restoreState(el);
  });

  // Save state
  persistentElements.forEach((el) => {
    saveState(el);
  });
}

// Call the function to replace the div with the select element
replaceDivWithSelect();

// Handle updating persistence when the DOM is updated.
const observeDOM = () => {
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.addedNodes) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.matches(".persistent")) {
            restoreState(node);
            node.addEventListener("change", () => saveState(node));
          }
        });
      }
    });
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
};

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
