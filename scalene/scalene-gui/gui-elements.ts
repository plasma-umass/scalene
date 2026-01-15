import { memory_consumed_str, time_consumed_str } from "./utils";

export const Lightning = "&#9889;"; // lightning bolt (for optimizing a line)
export const Explosion = "&#128165;"; // explosion (for optimizing a region)
export const WhiteLightning = `<span style="opacity:0">${Lightning}</span>`; // invisible but same width as lightning bolt
export const WhiteExplosion = `<span style="opacity:0">${Explosion}</span>`; // invisible but same width as explosion
export const RightTriangle = "&#9658"; // right-facing triangle symbol (collapsed view)
export const DownTriangle = "&#9660"; // downward-facing triangle symbol (expanded view)

// Type for chart parameters
export interface ChartParams {
  width: number;
  height: number;
}

// Type for profile data - extending globalThis
declare global {
  interface Window {
    profile?: {
      elapsed_time_sec: number;
      [key: string]: unknown;
    };
  }
  // eslint-disable-next-line no-var
  var profile: {
    elapsed_time_sec: number;
    max_footprint_mb: number;
    growth_rate: number;
    gpu: boolean;
    gpu_device: string;
    memory: boolean;
    samples: Array<[number, number]>;
    files: Record<string, FileProfile>;
    program?: string;
    stacks?: unknown;
  };
}

export interface LineProfile {
  lineno: number;
  line: string;
  n_cpu_percent_python: number;
  n_cpu_percent_c: number;
  n_sys_percent: number;
  n_gpu_percent: number;
  n_gpu_peak_memory_mb: number;
  n_peak_mb: number;
  n_avg_mb: number;
  n_python_fraction: number;
  n_usage_fraction: number;
  n_copy_mb_s: number;
  n_copy_mb: number;
  n_malloc_mb: number;
  n_core_utilization: number;
  memory_samples: Array<[number, number]>;
  start_region_line: number;
  end_region_line: number;
  nrt_time_ms?: number;
  nrt_percent?: number;
  nc_time_ms?: number;
  cpu_samples_nc_overlap_percent?: number;
}

export interface FileProfile {
  lines: LineProfile[];
  functions: LineProfile[];
  imports: string[];
  percent_cpu_time: number;
  leaks?: Record<number, { velocity_mb_s: number }>;
}

function makeTooltip(title: string, value: number): string {
  // Tooltip for time bars, below
  const secs = (value / 100) * globalThis.profile.elapsed_time_sec;
  return (
    `(${title}) ` +
    value.toFixed(1) +
    "%" +
    " [" +
    time_consumed_str(secs * 1e3) +
    "]"
  );
}

export function makeBar(
  python: number,
  native: number,
  system: number,
  params: ChartParams
): object {
  // Make a time bar
  const widthThreshold1 = 20;
  const widthThreshold2 = 10;
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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: python.toFixed(1),
          c: makeTooltip("Python", python),
          d:
            python >= widthThreshold1
              ? python.toFixed(0) + "%"
              : python >= widthThreshold2
                ? python.toFixed(0)
                : "",
          q: python / 2,
        },
        {
          x: 0,
          y: native.toFixed(1),
          c: makeTooltip("native", native),
          d:
            native >= widthThreshold1
              ? native.toFixed(0) + "%"
              : native >= widthThreshold2
                ? native.toFixed(0)
                : "",
          q: python + native / 2,
        },
        {
          x: 0,
          y: system.toFixed(1),
          c: makeTooltip("system", system),
          d:
            system >= widthThreshold1
              ? system.toFixed(0) + "%"
              : system >= widthThreshold2
                ? system.toFixed(0)
                : "",
          q: python + native + system / 2,
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            stack: "zero",
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
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
          tooltip: [{ field: "c", type: "nominal", title: "time" }],
        },
      },
    ],
  };
}

export function makeGPUPie(
  util: number,
  gpu_device: string,
  params: ChartParams
): object {
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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          category: 1,
          value: util.toFixed(1),
          c: "in use: " + util.toFixed(1) + "%",
        },
      ],
    },
    mark: "arc",
    encoding: {
      theta: {
        field: "value",
        type: "quantitative",
        scale: { domain: [0, 100] },
      },
      color: {
        field: "c",
        type: "nominal",
        legend: false,
        scale: { range: ["goldenrod", "#f4e6c2"] },
      },
      tooltip: [{ field: "c", type: "nominal", title: gpu_device }],
    },
  };
}

export function makeGPUBar(
  util: number,
  gpu_device: string,
  params: ChartParams
): object {
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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: util.toFixed(0),
          q: (util / 2).toFixed(0),
          d: util >= 20 ? util.toFixed(0) + "%" : "",
          dd: "in use: " + util.toFixed(0) + "%",
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            scale: { domain: [0, 100] },
          },
          color: {
            field: "dd",
            type: "nominal",
            legend: false,
            scale: { range: ["goldenrod", "#f4e6c2"] },
          },
          tooltip: [{ field: "dd", type: "nominal", title: gpu_device + ":" }],
        },
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
          tooltip: [{ field: "dd", type: "nominal", title: gpu_device + ":" }],
        },
      },
    ],
  };
}

export function makeMemoryPie(
  native_mem: number,
  python_mem: number,
  params: { width: number }
): object {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: params.width,
    height: 20,
    padding: 0,
    data: {
      values: [
        {
          category: 1,
          value: native_mem.toFixed(1),
          c: "native: " + native_mem.toFixed(1) + "%",
        },
        {
          category: 2,
          value: python_mem.toFixed(1),
          c: "Python: " + python_mem.toFixed(1) + "%",
        },
      ],
    },
    mark: "arc",
    encoding: {
      theta: {
        field: "value",
        type: "quantitative",
        scale: { domain: [0, 100] },
      },
      color: {
        field: "c",
        type: "nominal",
        legend: false,
        scale: { range: ["darkgreen", "#50C878"] },
      },
      tooltip: [{ field: "c", type: "nominal", title: "memory" }],
    },
  };
}

export function makeMemoryBar(
  memory: number | string,
  _title: string,
  python_percent: number,
  total: number | string,
  color: string,
  params: ChartParams
): object {
  const memoryNum = typeof memory === "string" ? parseFloat(memory) : memory;
  const totalNum = typeof total === "string" ? parseFloat(total) : total;

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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: python_percent * memoryNum,
          c: "(Python) " + memory_consumed_str(python_percent * memoryNum),
          d:
            python_percent * memoryNum > totalNum * 0.2
              ? memory_consumed_str(python_percent * memoryNum)
              : "",
          q: (python_percent * memoryNum) / 2,
        },
        {
          x: 0,
          y: (1.0 - python_percent) * memoryNum,
          c: "(native) " + memory_consumed_str((1.0 - python_percent) * memoryNum),
          d:
            (1.0 - python_percent) * memoryNum > totalNum * 0.2
              ? memory_consumed_str((1.0 - python_percent) * memoryNum)
              : "",
          q: python_percent * memoryNum + ((1.0 - python_percent) * memoryNum) / 2,
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            scale: { domain: [0, totalNum] },
          },
          color: {
            field: "c",
            type: "nominal",
            legend: false,
            scale: { range: [color, "#50C878", "green"] },
          },
        },
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
        },
      },
    ],
  };
}

export function makeSparkline(
  samples: Array<[number, number]>,
  max_x: number,
  max_y: number,
  leak_velocity: number = 0,
  params: ChartParams
): object {
  const values = samples.map((v) => {
    let leak_str = "";
    if (leak_velocity != 0) {
      leak_str = `; possible leak (${memory_consumed_str(leak_velocity)}/s)`;
    }
    return {
      x: v[0],
      y: v[1],
      y_text:
        memory_consumed_str(v[1]) +
        " (@ " +
        time_consumed_str(v[0] / 1e6) +
        ")" +
        leak_str,
    };
  });
  let leak_info = "";
  let height = params.height;
  if (leak_velocity != 0) {
    leak_info = "possible leak";
    height -= 10; // FIXME should be actual height of font
  }

  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: values },
    width: params.width,
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

export function makeNRTBar(
  nrt_time_ms: number,
  elapsed_time_sec: number,
  params: ChartParams
): object {
  const widthThreshold1 = 15;
  const widthThreshold2 = 8;

  const elapsed_time_ms = elapsed_time_sec * 1000;
  const nrt_percent =
    elapsed_time_ms > 0 ? (nrt_time_ms / elapsed_time_ms) * 100 : 0;

  const tooltipText =
    "NRT: " +
    nrt_percent.toFixed(1) +
    "% of elapsed time [" +
    time_consumed_str(nrt_time_ms) +
    "]";

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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: nrt_percent.toFixed(1),
          c: tooltipText,
          d:
            nrt_percent >= widthThreshold1
              ? nrt_percent.toFixed(0) + "%"
              : nrt_percent >= widthThreshold2
                ? nrt_percent.toFixed(0)
                : "",
          q: nrt_percent / 2,
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            stack: "zero",
            scale: { domain: [0, 100] },
          },
          color: {
            field: "c",
            type: "nominal",
            legend: false,
            scale: { range: ["purple"] },
          },
          tooltip: [{ field: "c", type: "nominal", title: "NRT time" }],
        },
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
          tooltip: [{ field: "c", type: "nominal", title: "NRT time" }],
        },
      },
    ],
  };
}

export function makeNCNRTPie(
  nc_time_ms: number,
  nrt_time_ms: number,
  params: ChartParams
): object {
  const total_time = nc_time_ms + nrt_time_ms;
  const nc_proportion = (nc_time_ms / total_time) * 100;
  const nrt_proportion = (nrt_time_ms / total_time) * 100;

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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          category: "NC",
          value: nc_time_ms,
          c:
            "NC: " +
            time_consumed_str(nc_time_ms) +
            " (" +
            nc_proportion.toFixed(1) +
            "%)",
        },
        {
          category: "NRT",
          value: nrt_time_ms,
          c:
            "NRT: " +
            time_consumed_str(nrt_time_ms) +
            " (" +
            nrt_proportion.toFixed(1) +
            "%)",
        },
      ],
    },
    mark: "arc",
    encoding: {
      theta: {
        field: "value",
        type: "quantitative",
      },
      color: {
        field: "category",
        type: "nominal",
        legend: false,
        scale: {
          domain: ["NC", "NRT"],
          range: ["darkorange", "white"],
        },
      },
      tooltip: [{ field: "c", type: "nominal", title: "NC vs NRT time" }],
    },
  };
}

export function makeNCTimeBar(
  nc_time_ms: number,
  elapsed_time_sec: number,
  params: ChartParams
): object {
  const widthThreshold1 = 15;
  const widthThreshold2 = 8;

  const elapsed_time_ms = elapsed_time_sec * 1000;
  const nc_percent =
    elapsed_time_ms > 0 ? (nc_time_ms / elapsed_time_ms) * 100 : 0;

  const tooltipText =
    "NC: " +
    nc_percent.toFixed(1) +
    "% of elapsed time [" +
    time_consumed_str(nc_time_ms) +
    "]";

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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: nc_percent.toFixed(1),
          c: tooltipText,
          d:
            nc_percent >= widthThreshold1
              ? nc_percent.toFixed(0) + "%"
              : nc_percent >= widthThreshold2
                ? nc_percent.toFixed(0)
                : "",
          q: nc_percent / 2,
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            stack: "zero",
            scale: { domain: [0, 100] },
          },
          color: {
            field: "c",
            type: "nominal",
            legend: false,
            scale: { range: ["darkorange"] },
          },
          tooltip: [{ field: "c", type: "nominal", title: "NC time" }],
        },
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
          tooltip: [{ field: "c", type: "nominal", title: "NC time" }],
        },
      },
    ],
  };
}

export function makeTotalNeuronBar(
  total_time_ms: number,
  elapsed_time_sec: number,
  label: string,
  color: string,
  params: ChartParams
): object {
  const widthThreshold1 = 15;
  const widthThreshold2 = 8;

  const elapsed_time_ms = elapsed_time_sec * 1000;
  const time_percent =
    elapsed_time_ms > 0 ? (total_time_ms / elapsed_time_ms) * 100 : 0;

  const tooltipText = `${label}: ${time_percent.toFixed(1)}% of elapsed time [${time_consumed_str(total_time_ms)}]`;

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
    width: params.width,
    height: params.height,
    padding: 0,
    data: {
      values: [
        {
          x: 0,
          y: time_percent.toFixed(1),
          c: tooltipText,
          d:
            time_percent >= widthThreshold1
              ? time_percent.toFixed(0) + "%"
              : time_percent >= widthThreshold2
                ? time_percent.toFixed(0)
                : "",
          q: time_percent / 2,
        },
      ],
    },
    layer: [
      {
        mark: { type: "bar" },
        encoding: {
          x: {
            aggregate: "sum",
            field: "y",
            axis: false,
            stack: "zero",
            scale: { domain: [0, 100] },
          },
          color: {
            field: "c",
            type: "nominal",
            legend: false,
            scale: { range: [color] },
          },
          tooltip: [{ field: "c", type: "nominal", title: label + " time" }],
        },
      },
      {
        mark: {
          type: "text",
          align: "center",
          baseline: "middle",
          dx: 0,
        },
        encoding: {
          x: {
            aggregate: "sum",
            field: "q",
            axis: false,
          },
          text: { field: "d" },
          color: { value: "white" },
          tooltip: [{ field: "c", type: "nominal", title: label + " time" }],
        },
      },
    ],
  };
}
