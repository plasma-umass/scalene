function vsNavigate(filename, lineno) {
    // If we are in VS Code, clicking on a line number in Scalene's web UI will navigate to that line in the source code.
    try {
	const vscode = acquireVsCodeApi();
        vscode.postMessage({
            command: 'jumpToLine',
            filePath: filename,
            lineNumber: lineno
        });
    } catch {
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
    }
  });
    return response;
}

async function isValidApiKey(apiKey) {
    const response = await tryApi(apiKey);
    const data = await response.json();
    if (data.error && (data.error.code in { "invalid_api_key" : true,
					    "invalid_request_error" : true,
					    "model_not_found" : true,
					    "insufficient_quota" : true })) {
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

function extractCode(text) {
  /**
  * Extracts code block from the given completion text.
  *
  * @param {string} text - A string containing text and other data.
  * @returns {string} Extracted code block from the completion object.
  */
    if (!text) {
	return text;
    }
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') {
    i++;
  }
    const first_line = lines[i].trim();
  let code_block;
  if (first_line === '```') {
    code_block = text.slice(3);
  } else if (first_line.startsWith('```')) {
    const word = first_line.slice(3).trim();
    if (word.length > 0 && !word.includes(' ')) {
      code_block = text.slice(first_line.length);
    } else {
      code_block = text;
    }
  } else {
    code_block = text;
  }
  const end_index = code_block.indexOf('```');
  if (end_index !== -1) {
    code_block = code_block.slice(0, end_index);
  }
  return code_block;
}

async function sendPromptToOpenAI(prompt, len, apiKey) {
    const endpoint = "https://api.openai.com/v1/chat/completions";
    const model = document.getElementById('language-model').value;
    
    const body = JSON.stringify({
	model: model,
	messages: [
	    {
		role: 'system',
		content: 'You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, starting with ``` and ending with ```.'
	    },
	    {
		role: 'user',
		content: prompt
	    }
	],
	temperature: 0.3,
	frequency_penalty: 0,
	presence_penalty: 0,
	user: "scalene-user"
    });

    console.log(body);
    
    const response = await fetch(endpoint, {
	method: "POST",
	headers: {
	    "Content-Type": "application/json",
	    Authorization: `Bearer ${apiKey}`,
	},
	body: body,
    });

    const data = await response.json();
    if (data.error) {
	if (data.error.code in { "invalid_request_error" : true,
				 "model_not_found" : true,
				 "insufficient_quota" : true }) {
	    if ((data.error.code === "model_not_found") && (model === "gpt-4")) {
		// Technically, model_not_found applies only for GPT-4.0
		// if an account has not been funded with at least $1.
		alert("You either need to add funds to your OpenAI account to use this feature, or you need to switch to GPT-3.5 if you are using free credits.");
	    } else {
		alert("You need to add funds to your OpenAI account to use this feature.");
	    }
	    return "";
	}
    }
    try {
	console.log(`Debugging info: Retrieved ${JSON.stringify(data.choices[0], null, 4)}`);
    } catch {
	console.log(`Debugging info: Failed to retrieve data.choices from the server. data = ${JSON.stringify(data)}`);
    }
    
    try {
	return data.choices[0].message.content.replace(/^\s*[\r\n]/gm, "");
    } catch {
	// return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
	return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
    }
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

async function optimizeCode(imports, code, context) {
    // Tailor prompt to request GPU optimizations or not.
    const useGPUs = document.getElementById('use-gpu-checkbox').checked; // globalThis.profile.gpu;
    const useGPUstring = useGPUs ? " or the GPU " : " ";
    // Check for a valid API key.
  const apiKey = document.getElementById("api-key").value;
  if (!apiKey) {
    alert(
      "To activate proposed optimizations, enter an OpenAI API key in advanced options."
    );
    return '';
  }
    // If the code to be optimized is just one line of code, say so.
    let lineOf = " ";
    if (code.split("\n").length <= 2) {
	lineOf = " line of ";
    }

    let libraries = 'import sklearn';
    if (useGPUs) {
	// Suggest cupy if we are using the GPU.
	libraries += '\nimport cupy';
    } else {
	// Suggest numpy otherwise.
	libraries += '\nimport numpy as np';
    }
    
    // Construct the prompt.

    const optimizePerformancePrompt = `Optimize the following${lineOf}Python code:\n\n${context}\n\n# Start of code\n\n${code}\n\n# End of code\n\nRewrite the above Python code only from "Start of code" to "End of code", to make it more efficient WITHOUT CHANGING ITS RESULTS. Assume the code has already executed all these imports; do NOT include them in the optimized code:\n\n${imports}\n\nUse native libraries if that would make it faster than pure Python. Consider using the following other libraries, if appropriate:\n\n${libraries}\n\nYour output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use vectorized operations${useGPUstring}whenever it would substantially increase performance, and quantify the speedup in terms of orders of magnitude. Eliminate as many for loops, while loops, and list or dict comprehensions as possible, replacing them with vectorized equivalents. If the performance is not likely to increase, leave the code unchanged. Fix any errors in the optimized code. Optimized${lineOf}code:`

    const pure_optimizePerformancePrompt = `Optimize the following${lineOf}Python code:\n\n${context}\n\n# Start of code\n\n${code}\n\n# End of code\n\nRewrite the above Python code only from "Start of code" to "End of code", to make it more efficient WITHOUT CHANGING ITS RESULTS. Assume the code has already executed all these imports; do NOT include them in the optimized code:\n\n${imports}\n\nONLY USE PURE PYTHON.\n\nYour output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. If the performance is not likely to increase, leave the code unchanged. Fix any errors in the optimized code. Optimized${lineOf}code:`

    const memoryEfficiencyPrompt = `Optimize the following${lineOf} Python code:\n\n${context}\n\n# Start of code\n\n${code}\n\n\n# End of code\n\nRewrite the above Python code only from "Start of code" to "End of code", to make it more memory-efficient WITHOUT CHANGING ITS RESULTS. Assume the code has already executed all these imports; do NOT include them in the optimized code:\n\n${imports}\n\nUse native libraries if that would make it more space efficient than pure Python. Consider using the following other libraries, if appropriate:\n\n${libraries}\n\nYour output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use native libraries whenever possible to reduce memory consumption; invoke del on variables and array elements as soon as it is safe to do so. If the memory consumption is not likely to be reduced, leave the code unchanged. Fix any errors in the optimized code. Optimized${lineOf}code:`

    const optimizePerf = document.getElementById('optimize-performance').checked;

    let prompt;
    if (optimizePerf) {
 	prompt = optimizePerformancePrompt;
    } else {
	prompt = memoryEfficiencyPrompt;
    }
    
    // const prompt = `Below is some Python code to optimize, from "Start of code" to "End of code":\n\n# Start of code\n\n${code}\n\n# End of code\n\nRewrite the above Python code to make it more efficient without changing the results. Assume the code has already executed these imports. Do NOT include them in the optimized code:\n\n${imports}\n\nUse fast native libraries if that would make it faster than pure Python. Your output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use vectorized operations${useGPUstring}whenever it would substantially increase performance, and quantify the speedup in terms of orders of magnitude. If the performance is not likely to increase, leave the code unchanged. Check carefully by generating inputs to see that the output is identical for both the original and optimized versions. Correctly-optimized code:`;

    console.log(prompt);
    
  // const prev_prompt =  `Below is some Python code to optimize:\n\n${code}\n\nRewrite the above Python code to make it more efficient while keeping the same semantics. Use fast native libraries if that would make it faster than pure Python. Your output should only consist of valid Python code. Output only the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use vectorized operations or the GPU whenever it would substantially increase performance, and try to quantify the speedup in terms of orders of magnitude. If the performance is not likely to increase, leave the code unchanged. Your output should only consist of legal Python code. Format all comments to be less than 40 columns wide:\n\n`;

    // Use number of words in the original code as a proxy for the number of tokens.
    const numWords = (code.match(/\b\w+\b/g)).length;

    const result = await sendPromptToOpenAI(prompt, Math.max(numWords * 4, 500), apiKey);
    return extractCode(result);
}

function proposeOptimizationRegion(filename, file_number, lineno) {
  proposeOptimization(filename, file_number, lineno, { regions: true });
}

function proposeOptimizationLine(filename, file_number, lineno) {
  proposeOptimization(filename, file_number, lineno, { regions: false });
}

function proposeOptimization(filename, file_number, lineno, params) {
    filename = unescape(filename)
  const useRegion = params["regions"];
  const prof = globalThis.profile;
  const this_file = prof.files[filename].lines;
  const imports = prof.files[filename].imports.join("\n");
  const start_region_line = this_file[lineno - 1]["start_region_line"];
  const end_region_line = this_file[lineno - 1]["end_region_line"];
    let context; 
  const code_line = this_file[lineno - 1]["line"];
  let code_region;
  if (useRegion) {
    code_region = this_file
      .slice(start_region_line - 1, end_region_line)
      .map((e) => e["line"])
      .join("");
    context = this_file.slice(Math.max(0, start_region_line - 10), Math.min(start_region_line - 1, this_file.length))
	  .map((e) => e["line"])
	  .join("");
  } else {
    code_region = code_line;
    context = this_file.slice(Math.max(0, lineno - 10), Math.min(lineno - 1, this_file.length))
	  .map((e) => e["line"])
	  .join("");
  }
  // Count the number of leading spaces to match indentation level on output
  let leadingSpaceCount = countSpaces(code_line) + 3; // including the lightning bolt and explosion
  let indent =
    WhiteLightning + WhiteExplosion + "&nbsp;".repeat(leadingSpaceCount - 1);
  const elt = document.getElementById(`code-${file_number}-${lineno}`);
  (async () => {
    const isValid = await isValidApiKey(
      document.getElementById("api-key").value
    );
    if (!isValid) {
	alert("You must enter a valid OpenAI API key to activate proposed optimizations.");
	return;
    }
    elt.innerHTML = `<em>${indent}working...</em>`;
      let message = await optimizeCode(imports, code_region, context);
    if (!message) {
      elt.innerHTML = "";
      return;
    }
    // Canonicalize newlines
    message = message.replace(new RegExp("\r?\n", "g"), "\n");
    // Indent every line and format it
    const formattedCode = message
      .split("\n")
      .map(
        (line) =>
          indent + Prism.highlight(line, Prism.languages.python, "python")
      )
	  .join("<br />");
      // Display the proposed optimization, with click-to-copy functionality.
      elt.innerHTML = `<hr><span title="click to copy" style="cursor: copy" id="opt-${file_number}-${lineno}">${formattedCode}</span>`;
      thisElt = document.getElementById(`opt-${file_number}-${lineno}`);
      thisElt.addEventListener("click",
			       async (e) => {
				   await copyOnClick(e, message);
				   // After copying, briefly change the cursor back to the default to provide some visual feedback..
				   thisElt.style = "cursor: auto";
				   await new Promise(resolve => setTimeout(resolve, 125));
				   thisElt.style = "cursor: copy";
			       });
  })();
}

async function copyOnClick(event, message) {
    event.preventDefault();
    event.stopPropagation();
    await navigator.clipboard.writeText(message);
}

function memory_consumed_str(size_in_mb) {
  // Return a string corresponding to amount of memory consumed.
  let gigabytes = Math.floor(size_in_mb / 1024);
  let terabytes = Math.floor(gigabytes / 1024);
  if (terabytes > 0) {
    return `${(size_in_mb / 1048576).toFixed(3)} TB`;
  } else if (gigabytes > 0) {
    return `${(size_in_mb / 1024).toFixed(3)} GB`;
  } else {
    return `${size_in_mb.toFixed(3)} MB`;
  }
}

function time_consumed_str(time_in_ms) {
  let hours = Math.floor(time_in_ms / 3600000);
  let minutes = Math.floor((time_in_ms % 3600000) / 60000);
  let seconds = Math.floor((time_in_ms % 60000) / 1000);
  let hours_exact = time_in_ms / 3600000;
  let minutes_exact = (time_in_ms % 3600000) / 60000;
  let seconds_exact = (time_in_ms % 60000) / 1000;
  if (hours > 0) {
    return `${hours.toFixed(0)}h:${minutes_exact.toFixed(
      0
    )}m:${seconds_exact.toFixed(3)}s`;
  } else if (minutes >= 1) {
    return `${minutes.toFixed(0)}m:${seconds_exact.toFixed(3)}s`;
  } else if (seconds >= 1) {
    return `${seconds_exact.toFixed(3)}s`;
  } else {
    return `${time_in_ms.toFixed(3)}ms`;
  }
}

function makeBar(python, native, system, params) {
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
          c: "(Python) " + python.toFixed(1) + "%",
          d: python.toFixed(0) + "%",
        },
        {
          x: 0,
          y: native.toFixed(1),
          c: "(native) " + native.toFixed(1) + "%",
          d: native.toFixed(0) + "%",
        },
        {
          x: 0,
          y: system.toFixed(1),
          c: "(system) " + system.toFixed(1) + "%",
          d: system.toFixed(0) + "%",
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
            field: "c",
            type: "nominal",
            legend: false,
            scale: { range: ["darkblue", "#6495ED", "blue"] },
          },
          tooltip: [{ field: "c", type: "nominal", title: "time" }],
        },
      },
      /*	  ,
      {
          mark: {
              type: "text",
              opacity: 1.0,
              color: "white",
              align: "right",
              limit: 50,
          },
          encoding: {
              x: { type: "quantitative", field: "y" },
              text: {
		  field: "d",
		  bandPosition: 0.5,
		  condition: { test: `datum['y'] < 20`, value: "" },
              },
          },
	  },
	  */
    ],
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
      width: 30,
      height: 20,
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
      tooltip: [{ field: "c", type: "nominal", title: "GPU" }],
    },
  };
}

function makeMemoryPie(native_mem, python_mem, params) {
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

function makeMemoryBar(memory, title, python_percent, total, color, params) {
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
          y: python_percent * memory,
          c: "(Python) " + memory_consumed_str(python_percent * memory),
        },
        {
          x: 0,
          y: (1.0 - python_percent) * memory,
          c: "(native) " + memory_consumed_str((1.0 - python_percent) * memory),
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
    params
) {
  const values = samples.map((v, i) => {
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
  if (leak_velocity != 0) {
    leak_info = "possible leak";
      params.height -= 10; // FIXME should be actual height of font
  }

  const strokeWidth = 1; // 0.25;
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: values },
    width: params.width,
    height: params.height,
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

function makeTableHeader(fname, gpu, memory, params) {
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
        title: ["memory", "average"],
        color: MemoryColor,
        width: 0,
        info: "Average amount of memory allocated by line / function",
      },
      {
        title: ["memory", "peak"],
        color: MemoryColor,
        width: 0,
        info: "Peak amount of memory allocated by line / function",
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
      title: ["gpu", "util."],
      color: CopyColor,
      width: 0,
      info: "% utilization of the GPU by line / function (may be inaccurate if GPU is not dedicated)",
    });
    columns.push({
      title: ["gpu", "memory"],
      color: CopyColor,
      width: 0,
      info: "Peak GPU memory allocated by line / function (may be inaccurate if GPU is not dedicated)",
    });
  }
  columns.push({ title: ["", ""], color: "black", width: 100 });
  let s = "";
  s += '<thead class="thead-light">';
  s += '<tr data-sort-method="thead">';
  for (const col of columns) {
      s += `<th class="F${escape(fname)}-nonline"><font style="font-variant: small-caps; text-decoration: underline; width:${col.width}" color=${col.color}>`;
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
  for (elt of elts) {
    s = elt.style;
    s.display = "none";
  }
}

function toggleReduced() {
  const elts = document.getElementsByClassName("empty-profile");
  for (elt of elts) {
    s = elt.style;
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
  propose_optimizations
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
    currline = prof["files"][filename]["lines"][lineno];
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
    total_time ||
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
	  { height: 20, width: 100 }
      )
    );
  } else {
    cpu_bars.push(null);
  }
  if (prof.memory) {
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
          parseFloat(line.n_python_fraction),
          prof.max_footprint_mb.toFixed(2),
            "darkgreen",
	    { height: 20, width: 100 }
        )
      );
    } else {
      memory_bars.push(null);
    }
    s += `<td style="height: 20; width: 100; vertical-align: middle" align="left" data-sort='${String(
      line.n_peak_mb.toFixed(0)
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
	    {height: 20, width: 75 }
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
            (1 - parseFloat(line.n_python_fraction)),
            100 * line.n_usage_fraction * parseFloat(line.n_python_fraction),
	    { width: 30 }
        )
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
  const empty_profile =
    total_time ||
    has_memory_results ||
    has_gpu_results ||
    end_region_line != start_region_line
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
  s += `<td style="height:10" align="left" bgcolor="whitesmoke" style="vertical-align: middle" data-sort="${line.lineno}">`;
  if (propose_optimizations && showExplosion) {
      s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for the entire region starting here." onclick="proposeOptimizationRegion('${escape(filename)}', ${file_number}, ${parseInt(
      line.lineno
    )}); event.preventDefault()">${regionOptimizationString}</span>`;
  } else {
    s += regionOptimizationString;
  }

  const lineOptimizationString = propose_optimizations
    ? `${Lightning}`
    : `${WhiteLightning}`;
  if (propose_optimizations) {
      s += `<span style="vertical-align: middle; cursor: pointer" title="Propose an optimization for this line." onclick="proposeOptimizationLine('${escape(filename)}', ${file_number}, ${parseInt(
      line.lineno
    )}); event.preventDefault()">${lineOptimizationString}</span>`;
  } else {
    s += lineOptimizationString;
  }
    s += `<pre style="height: 10; display: inline; white-space: pre-wrap; overflow-x: auto; border: 0px; vertical-align: middle"><code class="language-python ${empty_profile}">${codeLine}<span id="code-${file_number}-${line.lineno}" bgcolor="white"></span></code></pre></td>`;
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

// Track all profile ids so we can collapse and expand them en masse.
let allIDs = [];

function collapseAll() {
  for (const id of allIds) {
    collapseDisplay(id);
  }
}

function expandAll() {
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

function toggleDisplay(id) {
  const d = document.getElementById(`profile-${id}`);
  if (d.style.display == "block") {
    d.style.display = "none";
    document.getElementById(`button-${id}`).innerHTML = RightTriangle;
  } else {
    d.style.display = "block";
    document.getElementById(`button-${id}`).innerHTML = DownTriangle;
  }
}

async function display(prof) {
  // Clear explosions.
  showedExplosion = {};
    // Restore the API key from local storage (if any).
    let old_key = '';
    old_key = window.localStorage.getItem("scalene-api-key");
    
  if (old_key) {
    document.getElementById("api-key").value = old_key;
    // Update the status.
    checkApiKey(old_key);
  }

    // Restore the old GPU toggle from local storage (if any).
    const gpu_checkbox = document.getElementById('use-gpu-checkbox')
    old_gpu_checkbox = window.localStorage.getItem("scalene-gpu-checkbox");
    if (old_gpu_checkbox) {
	if (gpu_checkbox.checked.toString() != old_gpu_checkbox) {
	    gpu_checkbox.click();
	}
    } else {
	// Set the GPU checkbox on if the profile indicated the presence of a GPU.
	if (gpu_checkbox.checked != prof.gpu) {
	    gpu_checkbox.click();
	}
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
    cpu_bars.push(makeBar(cpu_python, cpu_native, cpu_system, { height: 20, width: 200 }));
  if (prof.memory) {
    memory_bars.push(
      makeMemoryBar(
        max_alloc,
        "memory",
        mem_python / max_alloc,
        max_alloc,
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
  for (const ff of files) {
    const id = `file-${fileIteration}`;
    allIds.push(id);
      s += '<p class="text-left sticky-top bg-white bg-opacity-75" style="backdrop-filter: blur(2px);">';
    s += `<span id="button-${id}" title="Click to show or hide profile." style="cursor: pointer; color: blue" onClick="toggleDisplay('${id}')">`;
    s += `${DownTriangle}`;
    s += "</span>";
    s += `<font style="font-size: 90%"><code>${
      ff[0]
    }</code>: % of time = ${ff[1].percent_cpu_time.toFixed(
      1
    )}% (${time_consumed_str(
      (ff[1].percent_cpu_time / 100.0) * prof.elapsed_time_sec * 1e3
    )}) out of ${time_consumed_str(prof.elapsed_time_sec * 1e3)}.</font></p>`;
    s += `<div style="display: block" id="profile-${id}">`;
    s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
    tableID++;
      s += makeTableHeader(ff[0], prof.gpu, prof.memory, { functions: false });
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
          s += `<td class="F${
            escape(ff[0])
          }-blankline" style="line-height: 1px; background-color: lightgray" data-sort="${
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
        true
      );
    }
    s += "</tbody>";
    s += "</table>";
    // Print out function summaries.
    if (prof.files[ff[0]].functions.length) {
      s += `<table class="profile table table-hover table-condensed" id="table-${tableID}">`;
	s += makeTableHeader(ff[0], prof.gpu, prof.memory, { functions: true });
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
          false // no optimizations here
        );
      }
      s += "</table>";
    }
    s += "</div>";
    fileIteration++;
    // Insert empty lines between files.
    if (fileIteration < files.length) {
      s += "<hr>";
    }
  }
  s += "</div>";
  const p = document.getElementById("profile");
  p.innerHTML = s;

  // Logic for turning on and off the gray line separators.

  // If you click on any header to sort (except line profiles), turn gray lines off.
  for (const ff of files) {
      const allHeaders = document.getElementsByClassName(`F${escape(ff[0])}-nonline`);
    for (let i = 0; i < allHeaders.length; i++) {
      allHeaders[i].addEventListener("click", (e) => {
          const all = document.getElementsByClassName(`F${escape(ff[0])}-blankline`);
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
      .addEventListener("click", (e) => {
          const all = document.getElementsByClassName(`F${escape(ff[0])}-blankline`);
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
  memory_activity.forEach((p, index) => {
    if (p) {
      (async () => {
        await vegaEmbed(`#memory_activity${index}`, p, { actions: false });
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
  // Hide all empty profiles by default.
  hideEmptyProfiles();
  if (prof.program) {
    document.title = "Scalene - " + prof.program;
  } else {
    document.title = "Scalene";
  }
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
