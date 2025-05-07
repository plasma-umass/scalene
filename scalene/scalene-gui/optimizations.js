import { sendPromptToOpenAI } from "./openai";
import { sendPromptToOllama } from "./ollama";
import { sendPromptToAmazon } from "./amazon";
import { sendPromptToAzureOpenAI } from "./azure";

import { countSpaces } from "./utils";
import { isValidApiKey } from "./openai";

import { WhiteLightning, WhiteExplosion} from "./gui-elements";

async function copyOnClick(event, message) {
  event.preventDefault();
  event.stopPropagation();
  await navigator.clipboard.writeText(message);
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
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length && lines[i].trim() === "") {
    i++;
  }
  const first_line = lines[i].trim();
  let code_block;
  if (first_line === "```") {
    code_block = text.slice(3);
  } else if (first_line.startsWith("```")) {
    const word = first_line.slice(3).trim();
    if (word.length > 0 && !word.includes(" ")) {
      code_block = text.slice(first_line.length);
    } else {
      code_block = text;
    }
  } else {
    code_block = text;
  }
  const end_index = code_block.indexOf("```");
  if (end_index !== -1) {
    code_block = code_block.slice(0, end_index);
  }
  return code_block;
}


function generateScaleneOptimizedCodeRequest(
  context,
  sourceCode,
  line,
  recommendedLibraries = [],
    includeGpuOptimizations = false,
    GPUdeviceName = "GPU",
) {
  // Default high-performance libraries known for their efficiency
  const defaultLibraries = [
    "NumPy",
    "Scikit-learn",
    "Pandas",
    "TensorFlow",
    "PyTorch",
  ];
  const highPerformanceLibraries = [
    ...new Set([...defaultLibraries, ...recommendedLibraries]),
  ];

  let promptParts = [
    "Optimize the following Python code to make it more efficient WITHOUT CHANGING ITS RESULTS.\n\n",
    context.trim(),
    "\n# Start of code\n",
    sourceCode.trim(),
    "\n# End of code\n\n",
    "Rewrite the above Python code from 'Start of code' to 'End of code', aiming for clear and simple optimizations. ",
    "Your output should consist only of valid Python code, with brief explanatory comments prefaced with #. ",
    "Include a detailed explanatory comment before the code, starting with '# Proposed optimization:'. ",
      `Leverage high-performance native libraries, especially those utilizing ${GPUdeviceName}, for significant performance improvements. `,
    "Consider using the following other libraries, if appropriate:\n",
    highPerformanceLibraries.map((e) => "  import " + e).join("\n") + "\n",
    "Eliminate as many for loops, while loops, and list or dict comprehensions as possible, replacing them with vectorized equivalents. ",
    //    "Consider GPU utilization, memory consumption, and copy volume when using GPU-accelerated libraries. ",
    //    "Low GPU utilization and high copy volume indicate inefficient use of such libraries. ",
    "Quantify the expected speedup in terms of orders of magnitude if possible. ",
    "Fix any errors in the optimized code. ",
    //    "Consider the peak amount of memory used per line and CPU utilization for targeted optimization. ",
    //    "Note on CPU utilization: Low utilization in libraries known for multi-threading/multi-processing indicates inefficiency.\n\n",
  ];

  // Conditional inclusion of GPU optimizations
  if (includeGpuOptimizations) {
    promptParts.push(
	`Use ${GPUdeviceName}-accelerated libraries whenever it would substantially increase performance. `,
    );
  }

  // Performance Insights
  promptParts.push(
    "Consider the following insights gathered from the Scalene profiler for optimization:\n",
  );
  const total_cpu_percent =
    line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;

  promptParts.push(
    `- CPU time: percent spent in the Python interpreter: ${((100 * line.n_cpu_percent_python) / total_cpu_percent).toFixed(2)}%\n`,
  );
  promptParts.push(
    `- CPU time: percent spent executing native code: ${((100 * line.n_cpu_percent_c) / total_cpu_percent).toFixed(2)}%\n`,
  );
  promptParts.push(
    `- CPU time: percent of system time: ${((100 * line.n_sys_percent) / total_cpu_percent).toFixed(2)}%\n`,
  );
  // `- CPU utilization: ${performanceMetrics.cpu_utilization}. Low utilization with high-core count might indicate inefficient use of multi-threaded/multi-process libraries.\n`,
  promptParts.push(
    `- Core utilization: ${((100 * line.n_core_utilization) / total_cpu_percent).toFixed(2)}%\n`,
  );
  //      `- Peak memory per line: Focus on lines with high memory usage, specifically ${performanceMetrics.peak_memory_per_line}.\n`,
  promptParts.push(
    `- Peak memory usage: ${line.n_peak_mb.toFixed(0)}MB (${(100 * line.n_python_fraction).toFixed(2)}% Python memory)\n`,
  );
  //      `- Copy volume: ${performanceMetrics.copy_volume} MB. High volume indicates inefficient data handling with GPU libraries.\n`,
  if (line.n_copy_mb_s > 1) {
    promptParts.push(
      `- Megabytes copied per second by memcpy/strcpy: ${line.n_copy_mb_s.toFixed(2)}\n`,
    );
  }
  if (includeGpuOptimizations) {
    // `  - GPU utilization: ${performanceMetrics.gpu_utilization}%. Low utilization indicates potential inefficiencies in GPU-accelerated library use.\n`
    promptParts.push(
      `- GPU percent utilization: ${(100 * line.n_gpu_percent).toFixed(2)}%\n`,
    );
    // `  - GPU memory usage: ${performanceMetrics.gpu_memory} MB. Optimize to reduce unnecessary GPU memory consumption.\n`
    // TODO GPU memory
  }
  promptParts.push(`Optimized code:`);
  return promptParts.join("");
}


function extractPythonCodeBlock(markdown) {
  // Pattern to match code blocks optionally tagged with "python"
  // - ``` optionally followed by "python"
  // - Non-greedy match for any characters (including new lines) between the backticks
  // - Flags:
  //   - 'g' for global search to find all matches
  //   - 's' to allow '.' to match newline characters
  const pattern = /```python\s*([\s\S]*?)```|```([\s\S]*?)```/g;

  let match;
  let extractedCode = "";
  // Use a loop to find all matches
  while ((match = pattern.exec(markdown)) !== null) {
    // Check which group matched. Group 1 is for explicitly tagged Python code, group 2 for any code block
    const codeBlock = match[1] ? match[1] : match[2];
    // Concatenate the extracted code blocks, separated by new lines if there's more than one block
    if (extractedCode && codeBlock) extractedCode += "\n\n";
    extractedCode += codeBlock;
  }

  return extractedCode;
}

export async function optimizeCode(imports, code, line, context) {
  // Tailor prompt to request GPU optimizations or not.
  const useGPUs = document.getElementById("use-gpu-checkbox").checked; // globalThis.profile.gpu;

  let recommendedLibraries = ["sklearn"];
  if (useGPUs) {
    // Suggest cupy if we are using the GPU.
    recommendedLibraries.push("cupy");
  } else {
    // Suggest numpy otherwise.
    recommendedLibraries.push("numpy");
  }
  // TODO: remove anything already imported in imports

  const GPUdeviceName = document.getElementById("accelerator-name").innerHTML || "GPU";
    
  const bigPrompt = generateScaleneOptimizedCodeRequest(
    context,
    code,
    line,
    recommendedLibraries,
    useGPUs,
    GPUdeviceName
  );

  
    const useGPUstring = useGPUs ? ` or ${GPUdeviceName}-optimizations ` : " ";
  // Check for a valid API key.
  // TODO: Add checks for Amazon / local
  let apiKey = "";
  let aiService = document.getElementById("service-select").value;
  if (aiService === "openai") {
    apiKey = document.getElementById("api-key").value;
    endpoint = document.getElementById("url-openai-compatibility").value;
  } else if (aiService === "azure-openai") {
    apiKey = document.getElementById("azure-api-key").value;
  }

  if ((aiService === "openai" || aiService === "azure-openai") && !apiKey) {
    alert(
      "To activate proposed optimizations, enter an OpenAI API key in AI optimization options.",
    );
    document.getElementById("ai-optimization-options").open = true;
    return "";
  }
  // If the code to be optimized is just one line of code, say so.
  let lineOf = " ";
  if (code.split("\n").length <= 2) {
    lineOf = " line of ";
  }

  let libraries = "import sklearn";
  if (useGPUs) {
    // Suggest cupy if we are using the GPU.
    libraries += "\nimport cupy";
  } else {
    // Suggest numpy otherwise.
    libraries += "\nimport numpy as np";
  }

  // Construct the prompt.

  const optimizePerformancePrompt = `Optimize the following${lineOf}Python code:\n\n${context}\n\n# Start of code\n\n${code}\n\n# End of code\n\nRewrite the above Python code only from "Start of code" to "End of code", to make it more efficient WITHOUT CHANGING ITS RESULTS. Assume the code has already executed all these imports; do NOT include them in the optimized code:\n\n${imports}\n\nUse native libraries if that would make it faster than pure Python. Consider using the following other libraries, if appropriate:\n\n${libraries}\n\nYour output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use vectorized operations${useGPUstring}whenever it would substantially increase performance, and quantify the speedup in terms of orders of magnitude. Eliminate as many for loops, while loops, and list or dict comprehensions as possible, replacing them with vectorized equivalents. If the performance is not likely to increase, leave the code unchanged. Fix any errors in the optimized code. Optimized${lineOf}code:`;

  const memoryEfficiencyPrompt = `Optimize the following${lineOf} Python code:\n\n${context}\n\n# Start of code\n\n${code}\n\n\n# End of code\n\nRewrite the above Python code only from "Start of code" to "End of code", to make it more memory-efficient WITHOUT CHANGING ITS RESULTS. Assume the code has already executed all these imports; do NOT include them in the optimized code:\n\n${imports}\n\nUse native libraries if that would make it more space efficient than pure Python. Consider using the following other libraries, if appropriate:\n\n${libraries}\n\nYour output should only consist of valid Python code. Output the resulting Python with brief explanations only included as comments prefaced with #. Include a detailed explanatory comment before the code, starting with the text "# Proposed optimization:". Make the code as clear and simple as possible, while also making it as fast and memory-efficient as possible. Use native libraries whenever possible to reduce memory consumption; invoke del on variables and array elements as soon as it is safe to do so. If the memory consumption is not likely to be reduced, leave the code unchanged. Fix any errors in the optimized code. Optimized${lineOf}code:`;

  const optimizePerf = document.getElementById("optimize-performance").checked;

  let prompt;
  if (optimizePerf) {
    prompt = optimizePerformancePrompt;
  } else {
    prompt = memoryEfficiencyPrompt;
  }

  // Just use big prompt maybe FIXME
  prompt = bigPrompt;

  switch (document.getElementById("service-select").value) {
    case "openai": {
      console.log(prompt);
      const result = await sendPromptToOpenAI(
        prompt,
        apiKey,
        endpoint,
      );
      return extractCode(result);
    }
    case "local": {
      console.log("Running " + document.getElementById("service-select").value);
      console.log(prompt);
      //      console.log(optimizePerformancePrompt_ollama);
      const result = await sendPromptToOllama(
        prompt, // optimizePerformancePrompt_ollama,
        document.getElementById("language-model-local").value,
        document.getElementById("local-ip").value,
        document.getElementById("local-port").value,
      );
      if (result.includes("```")) {
        return extractPythonCodeBlock(result);
      } else {
        return result;
      }
    }
    case "amazon": {
      console.log("Running " + document.getElementById("service-select").value);
      console.log(prompt);
      const result = await sendPromptToAmazon(
        prompt,
      );
      return extractCode(result);
    }
    case "azure-openai": {
      console.log("Running " + document.getElementById("service-select").value);
      console.log(prompt);
      let azureOpenAiEndpoint = document.getElementById("azure-api-url").value;
      let azureOpenAiModel = document.getElementById("azure-api-model").value;
      const result = await sendPromptToAzureOpenAI(
        prompt,
        apiKey,
        azureOpenAiEndpoint,
        azureOpenAiModel,
      );
      return extractCode(result);
    }
  }
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
