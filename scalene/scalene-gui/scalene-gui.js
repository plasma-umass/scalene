function makeBar(python, native, system) {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    config: {
      view: {
        stroke: "transparent",
      },
    },
    autosize: {
      contains: "padding",
    },
    width: "container",
    height: "container",
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: python.toFixed(1),
          c: "(Python) " + python.toFixed(1) + "%",
        },
        {
          x: 0,
          y: native.toFixed(1),
          c: "(native) " + native.toFixed(1) + "%",
        },
        {
          x: 0,
          y: system.toFixed(1),
          c: "(system) " + system.toFixed(1) + "%",
        },
      ],
    },
    mark: { type: "bar" },
    encoding: {
      x: {
        aggregate: "sum",
        field: "y",
        axis: false,
        scale: { domain: [0, 100] },
      },
      color: {
        field: "c",
        type: "nominal",
        legend: false,
        scale: { range: ["darkblue", "#6495ED", "blue"] },
      },
      tooltip: [{ field: "c", type: "nominal", title: "time" }],
    },
  };
}

function makeGPUPie(util) {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    config: {
      view: {
        stroke: "transparent",
      },
    },
    autosize: {
      contains: "padding",
    },
    width: "container",
    height: "container",
    padding: 0,
    data: {
      values: [
        {
          category: 1,
          value: util.toFixed(1),
          c: "in use: " + util.toFixed(1) + "%",
        },
        {
          category: 2,
          value: 100 - util.toFixed(1),
          c: "idle: " + (100 - util).toFixed(1) + "%",
        },
      ],
    },
    mark: "arc",
    encoding: {
      //"x": {"aggregate": "sum", "field": "y", "axis": false,
      //	  "scale" : { "domain" : [0, 100] } },
      theta: { field: "value", type: "quantitative" },
      color: {
        field: "c",
        type: "nominal",
        legend: false,
        scale: { range: ["#f4e6c2", "goldenrod"] },
      },
      tooltip: [{ field: "c", type: "nominal", title: "GPU" }],
    },
  };
}

function makeMemoryBar(memory, title, python_percent, total, color) {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    config: {
      view: {
        stroke: "transparent",
      },
    },
    autosize: {
      contains: "padding",
    },
    width: "container",
    height: "container",
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: python_percent * memory,
          c: "(Python) " + (python_percent * memory).toFixed(1) + "MB",
        },
        {
          x: 0,
          y: (1.0 - python_percent) * memory,
          c: "(native) " + ((1.0 - python_percent) * memory).toFixed(1) + "MB",
        },
      ],
    },
    mark: { type: "bar" },
    encoding: {
      x: {
        aggregate: "sum",
        field: "y",
        axis: false,
        scale: { domain: [0, total] },
      },
      color: {
        field: "c",
        type: "nominal",
        legend: false,
        scale: { range: [color, "#50C878", "green"] },
      },
      tooltip: [{ field: "c", type: "nominal", title: title }],
    },
  };
}

function makeSparkline(
  samples,
  max_x,
  max_y,
  leak_velocity = 0,
  height = 20,
  width = 75
) {
  const values = samples.map((v, i) => {
    let leak_str = "";
    if (leak_velocity != 0) {
      leak_str = `; possible leak (${leak_velocity.toFixed(1)} MB/s)`;
    }
    return {
      x: v[0],
      y: v[1],
      y_text:
        v[1].toFixed(1) + "MB (@ " + (v[0] / 1e9).toFixed(0) + "s)" + leak_str,
    };
  });
  let leak_info = "";
  if (leak_velocity != 0) {
    leak_info = "possible leak";
    height -= 10; // FIXME should be actual height of font
  }

  const strokeWidth = 1; // 0.25;
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: values },
    width: width,
    height: height,
    padding: 0,
    title: {
      text: leak_info,
      baseline: "line-bottom",
      color: "red",
      offset: 0,
      lineHeight: 10,
      orient: "bottom",
      fontStyle: "italic",
    },
    encoding: {
      x: {
        field: "x",
        type: "quantitative",
        title: "",
        axis: {
          tickCount: 10,
          tickSize: 0,
          labelExpr: "",
        },
        scale: {
          domain: [0, max_x],
        },
      },
    },
    layer: [
      {
        encoding: {
          y: {
            field: "y",
            type: "quantitative",
            axis: null,
            scale: {
              domain: [0, max_y],
            },
          },
          color: {
            field: "c",
            type: "nominal",
            legend: null,
            scale: {
              range: ["darkgreen"],
            },
          },
        },

        layer: [
          { mark: "line" },
          {
            transform: [{ filter: { param: "hover", empty: false } }],
            mark: "point",
          },
        ],
      },

      {
        mark: "rule",
        encoding: {
          opacity: {
            condition: { value: 0.3, param: "hover", empty: false },
            value: 0,
          },
          tooltip: [{ field: "y_text", type: "nominal", title: "memory" }],
        },
        params: [
          {
            name: "hover",
            select: {
              type: "point",
              fields: ["y"],
              nearest: true,
              on: "mousemove",
            },
          },
        ],
      },
    ],
  };
}

const CPUColor = "blue";
const MemoryColor = "green";
const CopyColor = "goldenrod";
let columns = [];

function makeTableHeader(fname, gpu, memory, functions = false) {
  let tableTitle;
  if (functions) {
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
        title: ["memory", "average"],
        color: MemoryColor,
        width: 0,
        info: "Average amount of memory allocated by this line / function",
      },
      {
        title: ["memory", "peak"],
        color: MemoryColor,
        width: 0,
        info: "Peak amount of memory allocated by this line / function",
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
        info: "% of bytes allocated by this line / function over the total bytes allocated in that file",
      },
      {
        title: ["copy", "(MB/s)"],
        color: CopyColor,
        width: 0,
        info: "Rate of copying memory, in megabytes per second",
      },
    ]);
  }
  if (gpu) {
    columns.push({
      title: ["gpu", "util."],
      color: CopyColor,
      width: 0,
      info: "% utilization of the GPU by this line / function (may be inaccurate if GPU is not dedicated)",
    });
    columns.push({
      title: ["gpu", "memory"],
      color: CopyColor,
      width: 0,
      info: "Peak GPU memory allocated by this line / function (may be inaccurate if GPU is not dedicated)",
    });
  }
  columns.push({ title: ["", ""], color: "black", width: 100 });
  let s = "";
  s += '<thead class="thead-light">';
  s += '<tr data-sort-method="thead">';
  for (const col of columns) {
    s += `<th class="F${fname}-nonline"><font style="font-variant: small-caps; text-decoration: underline; width:${col.width}" color=${col.color}>`;
    if (col.info) {
      s += `<a style="cursor:pointer;" title="${col.info}">${col.title[0]}</a>`;
    } else {
      s += `<a style="cursor:pointer;">${col.title[0]}</a>`;
    }
    s += "</font>&nbsp;&nbsp;</th>";
  }
  let id;
  if (functions) {
    id = "functionProfile";
  } else {
    id = "lineProfile";
  }
  s += `<th id=${
    fname + "-" + id
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

function makeProfileLine(
  line,
  filename,
  prof,
  cpu_bars,
  memory_bars,
  memory_sparklines,
  gpu_pies
) {
  let s = "";
  s += "<tr>";
  const total_time =
    line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;
  const total_time_str = String(total_time.toFixed(1)).padStart(10, " ");
  s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${total_time_str}'>`;
  s += `<span style="height: 20; width: 100; vertical-align: middle" id="cpu_bar${cpu_bars.length}"></span>`;
  cpu_bars.push(
    makeBar(line.n_cpu_percent_python, line.n_cpu_percent_c, line.n_sys_percent)
  );
  if (prof.memory) {
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_avg_mb.toFixed(0)
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    s += "</td>";
    memory_bars.push(
      makeMemoryBar(
        line.n_avg_mb.toFixed(0),
        "average memory",
        parseFloat(line.n_python_fraction),
        prof.max_footprint_mb.toFixed(2),
        "darkgreen"
      )
    );
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_peak_mb.toFixed(0)
    ).padStart(10, "0")}'>`;
    s += `<span style="height: 20; width: 100; vertical-align: middle" id="memory_bar${memory_bars.length}"></span>`;
    memory_bars.push(
      makeMemoryBar(
        line.n_peak_mb.toFixed(0),
        "peak memory",
        parseFloat(line.n_python_fraction),
        prof.max_footprint_mb.toFixed(2),
        "darkgreen"
      )
    );
    s += "</td>";
    s += `<td style='vertical-align: middle; width: 100'><span style="height:25; width: 100; vertical-align: middle" id="memory_sparkline${memory_sparklines.length}"></span>`;
    s += "</td>";
    if (line.memory_samples.length > 0) {
      let leak_velocity = 0;
      if (line.lineno in prof.files[filename].leaks) {
        leak_velocity = prof.files[filename].leaks[line.lineno].velocity_mb_s;
      }
      memory_sparklines.push(
        makeSparkline(
          line.memory_samples,
          prof.elapsed_time_sec * 1e9,
          prof.max_footprint_mb,
          leak_velocity
        )
      );
    } else {
      memory_sparklines.push(null);
    }
    s += '<td style="width: 100; vertical-align: middle" align="right">';
    if (line.n_usage_fraction >= 0.01) {
      s += `<font style="font-size: small">${String(
        (100 * line.n_usage_fraction).toFixed(0)
      ).padStart(10, " ")}%&nbsp;&nbsp;&nbsp;</font>`;
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
  if (prof.gpu) {
    if (line.n_gpu_percent < 1.0) {
      s += '<td style="width: 100"></td>';
    } else {
      //	    s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${line.n_gpu_percent.toFixed(0)}%</font></td>`;
      s += `<td style="width: 50; vertical-align: middle" align="right" data-sort="${line.n_gpu_percent}">`;
      s += `<span style="height: 20; width: 30; vertical-align: middle" id="gpu_pie${gpu_pies.length}"></span>`;
      s += "</td>";
      gpu_pies.push(makeGPUPie(line.n_gpu_percent));
    }
    if (true) {
      if (line.n_gpu_peak_memory_mb < 1.0 || line.n_gpu_percent < 1.0) {
        s += '<td style="width: 100"></td>';
      } else {
        s += `<td style="width: 100; vertical-align: middle" align="right"><font style="font-size: small" color="${CopyColor}">${line.n_gpu_peak_memory_mb.toFixed(
          0
        )}</font></td>`;
      }
    }
  }
  s += `<td align="right" style="vertical-align: middle; width: 50" data-sort="${line.lineno}"><font color="gray" style="font-size: 70%; vertical-align: middle" >${line.lineno}&nbsp;</font></td>`;
  const codeLine = Prism.highlight(line.line, Prism.languages.python, "python");
  s += `<td style="height:10" align="left" bgcolor="whitesmoke" style="vertical-align: middle" data-sort="${line.lineno}"><pre style="height: 10; display: inline; white-space: pre-wrap; overflow-x: auto; border: 0px; vertical-align: middle"><code class="language-python">${codeLine}</code></pre></td>`;
  s += "</tr>";
  return s;
}

function buildAllocationMaps(prof, f) {
  let averageMallocs = {};
  let peakMallocs = {};
  for (const line of prof.files[f].lines) {
    const avg = parseFloat(line.n_avg_mb);
    if (!averageMallocs[avg]) {
      averageMallocs[avg] = [];
    }
    averageMallocs[avg].push(line.lineno);
    const peak = parseFloat(line.n_peak_mb);
    if (!peakMallocs[peak]) {
      peakMallocs[peak] = [];
    }
    peakMallocs[peak].push(line.lineno);
  }
  return [averageMallocs, peakMallocs];
}

async function display(prof) {
  let memory_sparklines = [];
  let cpu_bars = [];
  let gpu_pies = [];
  let memory_bars = [];
  let tableID = 0;
  let s = "";
  s += '<div class="row justify-content-center">';
  s += '<div class="col-auto">';
  s += '<table width="50%" class="table text-center table-condensed">';
  s += "<tr>";
  s += `<td><font style="font-size: small"><b>Time:</b> <font color="darkblue">Python</font> | <font color="#6495ED">native</font> | <font color="blue">system</font><br /></font></td>`;
  s += '<td width="10"></td>';
  if (prof.memory) {
    s += `<td><font style="font-size: small"><b>Memory:</b> <font color="darkgreen">Python</font> | <font color="#50C878">native</font><br /></font></td>`;
    s += '<td width="10"></td>';
    s += '<td valign="middle" style="vertical-align: middle">';
    s += `<font style="font-size: small"><b>Memory timeline: </b>(max: ${prof.max_footprint_mb.toFixed(
      1
    )}MB, growth: ${prof.growth_rate.toFixed(1)}%)</font>`;
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
        20,
        200
      )
    );
  }
  s += "</tr>";

  // Compute overall usage.
  let cpu_python = 0;
  let cpu_native = 0;
  let cpu_system = 0;
  let mem_python = 0;
  let mem_native = 0;
  let max_alloc = 0;
  for (const f in prof.files) {
    let cp = 0;
    let cn = 0;
    let cs = 0;
    let mp = 0;
    for (const l in prof.files[f].lines) {
      const line = prof.files[f].lines[l];
      cp += line.n_cpu_percent_python;
      cn += line.n_cpu_percent_c;
      cs += line.n_sys_percent;
      mp += line.n_malloc_mb * line.n_python_fraction;
      max_alloc += line.n_malloc_mb;
    }
    cpu_python += cp;
    cpu_native += cn;
    cpu_system += cs;
    mem_python += mp;
  }
  cpu_bars.push(makeBar(cpu_python, cpu_native, cpu_system));
  if (prof.memory) {
    memory_bars.push(
      makeMemoryBar(
        max_alloc,
        "memory",
        mem_python / max_alloc,
        max_alloc,
        "darkgreen"
      )
    );
  }

  s += '<tr><td colspan="10">';
  s += `<p class="text-center"><font style="font-size: 90%; font-style: italic; font-color: darkgray">hover over bars to see breakdowns; click on <font style="font-variant:small-caps; text-decoration:underline">column headers</font> to sort.</font></p>`;
  s += "</td></tr>";
  s += "</table>";
  s += "</div>";
  s += "</div>";

  s += '<div class="container-fluid">';

  // Convert files to an array and sort it in descending order by percent of CPU time.
  files = Object.entries(prof.files);
  files.sort((x, y) => {
    return y[1].percent_cpu_time - x[1].percent_cpu_time;
  });

  // Print profile for each file
  let fileIteration = 0;
  for (const ff of files) {
    s += `<p class="text-left"><font style="font-size: 90%"><code>${
      ff[0]
    }</code>: % of time = ${ff[1].percent_cpu_time.toFixed(
      1
    )}% out of ${prof.elapsed_time_sec.toFixed(1)}s.</font></p>`;
    s += "<div>";
    s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
    tableID++;
    s += makeTableHeader(ff[0], prof.gpu, prof.memory, false);
    s += "<tbody>";
    // Print per-line profiles.
    let prevLineno = -1;
    for (const l in ff[1].lines) {
      const line = ff[1].lines[l];
      // Add a space whenever we skip a line.
      if (line.lineno > prevLineno + 1) {
        s += "<tr>";
        for (let i = 0; i < columns.length; i++) {
          s += "<td></td>";
        }
        s += `<td class="F${
          ff[0]
        }-blankline" style="line-height: 1px; background-color: lightgray" data-sort="${
          prevLineno + 1
        }">&nbsp;</td>`;
        s += "</tr>";
      }
      prevLineno = line.lineno;
      s += makeProfileLine(
        line,
        ff[0],
        prof,
        cpu_bars,
        memory_bars,
        memory_sparklines,
        gpu_pies
      );
    }
    s += "</tbody>";
    s += "</table>";
    // Print out function summaries.
    if (prof.files[ff[0]].functions.length) {
      s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
      s += makeTableHeader(ff[0], prof.gpu, prof.memory, true);
      s += "<tbody>";
      tableID++;
      for (const l in prof.files[ff[0]].functions) {
        const line = prof.files[ff[0]].functions[l];
        s += makeProfileLine(
          line,
          ff[0],
          prof,
          cpu_bars,
          memory_bars,
          memory_sparklines,
          gpu_pies
        );
      }
      s += "</table>";
    }
    s += "</div>";
    fileIteration++;
    // Insert empty lines between files.
    if (fileIteration < files.length) {
      s += "<p />&nbsp;<hr><p />&nbsp;<p />";
    }
  }
  s += "</div>";
  const p = document.getElementById("profile");
  p.innerHTML = s;

  // Logic for turning on and off the gray line separators.

  // If you click on any header to sort (except line profiles), turn gray lines off.
  for (const ff of files) {
    const allHeaders = document.getElementsByClassName(`F${ff[0]}-nonline`);
    for (let i = 0; i < allHeaders.length; i++) {
      allHeaders[i].addEventListener("click", (e) => {
        const all = document.getElementsByClassName(`F${ff[0]}-blankline`);
        for (let i = 0; i < all.length; i++) {
          all[i].style.display = "none";
        }
      });
    }
  }

  // If you click on the line profile header, and gray lines are off, turn them back on.
  for (const ff of files) {
    document
      .getElementById(`${ff[0]}-lineProfile`)
      .addEventListener("click", (e) => {
        const all = document.getElementsByClassName(`F${ff[0]}-blankline`);
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
  cpu_bars.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#cpu_bar${index}`, p, { actions: false });
      })();
    }
  });
  gpu_pies.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#gpu_pie${index}`, p, { actions: false });
      })();
    }
  });
  memory_bars.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#memory_bar${index}`, p, { actions: false });
      })();
    }
  });
  window.onload = () => {
    if (prof.program) {
      document.title = "Scalene - " + prof.program;
    } else {
      document.title = "Scalene";
    }
  };
}

function load(profile) {
  (async () => {
    // let resp = await fetch(jsonFile);
    // let prof = await resp.json();
    await display(profile);
  })();
}

function loadFetch() {
  (async () => {
    let resp = await fetch("profile.json");
    let profile = await resp.json();
    load(profile);
  })();
}

function loadFile() {
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

function loadDemo() {
  load(example_profile);
}
