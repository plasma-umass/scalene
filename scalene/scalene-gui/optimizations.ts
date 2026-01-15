import { sendPromptToOpenAI, isValidApiKey } from "./openai";
import { sendPromptToAnthropic } from "./anthropic";
import { sendPromptToGemini } from "./gemini";
import { sendPromptToOllama } from "./ollama";
import { sendPromptToAmazon } from "./amazon";
import { sendPromptToAzureOpenAI } from "./azure";
import { countSpaces } from "./utils";
import { WhiteLightning, WhiteExplosion } from "./gui-elements";

declare const Prism: {
  highlight: (code: string, grammar: unknown, language: string) => string;
  languages: { python: unknown };
};

declare const globalThis: {
  profile: {
    gpu: boolean;
    files: Record<string, {
      lines: LineData[];
      imports: string[];
    }>;
  };
};

interface LineData {
  lineno: number;
  line: string;
  n_cpu_percent_python: number;
  n_cpu_percent_c: number;
  n_sys_percent: number;
  n_core_utilization: number;
  n_peak_mb: number;
  n_python_fraction: number;
  n_copy_mb_s: number;
  n_copy_mb: number;
  n_gpu_percent: number;
  start_region_line: number;
  end_region_line: number;
}

interface OptimizationParams {
  regions: boolean;
}

async function copyOnClick(event: Event, message: string): Promise<void> {
  event.preventDefault();
  event.stopPropagation();
  await navigator.clipboard.writeText(message);
}

function extractCode(text: string): string {
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
  let code_block: string;
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
  context: string,
  sourceCode: string,
  line: LineData,
  recommendedLibraries: string[] = [],
  includeGpuOptimizations = false,
  GPUdeviceName = "GPU"
): string {
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

  const promptParts: string[] = [
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
    "Quantify the expected speedup in terms of orders of magnitude if possible. ",
    "Fix any errors in the optimized code. ",
  ];

  // Conditional inclusion of GPU optimizations
  if (includeGpuOptimizations) {
    promptParts.push(
      `Use ${GPUdeviceName}-accelerated libraries whenever it would substantially increase performance. `
    );
  }

  // Performance Insights
  promptParts.push(
    "Consider the following insights gathered from the Scalene profiler for optimization:\n"
  );
  const total_cpu_percent =
    line.n_cpu_percent_python + line.n_cpu_percent_c + line.n_sys_percent;

  promptParts.push(
    `- CPU time: percent spent in the Python interpreter: ${((100 * line.n_cpu_percent_python) / total_cpu_percent).toFixed(2)}%\n`
  );
  promptParts.push(
    `- CPU time: percent spent executing native code: ${((100 * line.n_cpu_percent_c) / total_cpu_percent).toFixed(2)}%\n`
  );
  promptParts.push(
    `- CPU time: percent of system time: ${((100 * line.n_sys_percent) / total_cpu_percent).toFixed(2)}%\n`
  );
  promptParts.push(
    `- Core utilization: ${((100 * line.n_core_utilization) / total_cpu_percent).toFixed(2)}%\n`
  );
  promptParts.push(
    `- Peak memory usage: ${line.n_peak_mb.toFixed(0)}MB (${(100 * line.n_python_fraction).toFixed(2)}% Python memory)\n`
  );
  if (line.n_copy_mb_s > 1) {
    promptParts.push(
      `- Megabytes copied per second by memcpy/strcpy: ${line.n_copy_mb_s.toFixed(2)}\n`
    );
  }
  if (includeGpuOptimizations) {
    promptParts.push(
      `- GPU percent utilization: ${(100 * line.n_gpu_percent).toFixed(2)}%\n`
    );
  }
  promptParts.push(`Optimized code:`);
  return promptParts.join("");
}

function extractPythonCodeBlock(markdown: string): string {
  // Pattern to match code blocks optionally tagged with "python"
  const pattern = /```python\s*([\s\S]*?)```|```([\s\S]*?)```/g;

  let match: RegExpExecArray | null;
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

export async function optimizeCode(
  imports: string,
  code: string,
  line: LineData,
  context: string
): Promise<string> {
  // Tailor prompt to request GPU optimizations or not.
  const useGPUCheckbox = document.getElementById("use-gpu-checkbox") as HTMLInputElement | null;
  const useGPUs = useGPUCheckbox?.checked ?? false;

  const recommendedLibraries: string[] = ["sklearn"];
  if (useGPUs) {
    // Suggest cupy if we are using the GPU.
    recommendedLibraries.push("cupy");
  } else {
    // Suggest numpy otherwise.
    recommendedLibraries.push("numpy");
  }

  const acceleratorNameElement = document.getElementById("accelerator-name");
  const GPUdeviceName = acceleratorNameElement?.innerHTML || "GPU";

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
  let apiKey = "";
  const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
  const aiService = serviceSelect?.value ?? "";

  if (aiService === "openai") {
    const apiKeyElement = document.getElementById("api-key") as HTMLInputElement | null;
    apiKey = apiKeyElement?.value ?? "";
  } else if (aiService === "anthropic") {
    const anthropicApiKeyElement = document.getElementById("anthropic-api-key") as HTMLInputElement | null;
    apiKey = anthropicApiKeyElement?.value ?? "";
  } else if (aiService === "gemini") {
    const geminiApiKeyElement = document.getElementById("gemini-api-key") as HTMLInputElement | null;
    apiKey = geminiApiKeyElement?.value ?? "";
  } else if (aiService === "azure-openai") {
    const azureApiKeyElement = document.getElementById("azure-api-key") as HTMLInputElement | null;
    apiKey = azureApiKeyElement?.value ?? "";
  }

  if ((aiService === "openai" || aiService === "azure-openai") && !apiKey) {
    alert(
      "To activate proposed optimizations, enter an OpenAI API key in AI optimization options."
    );
    const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
    if (aiOptOptions) {
      aiOptOptions.open = true;
    }
    return "";
  }

  if (aiService === "anthropic" && !apiKey) {
    alert(
      "To activate proposed optimizations, enter an Anthropic API key in AI optimization options."
    );
    const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
    if (aiOptOptions) {
      aiOptOptions.open = true;
    }
    return "";
  }

  if (aiService === "gemini" && !apiKey) {
    alert(
      "To activate proposed optimizations, enter a Google Gemini API key in AI optimization options."
    );
    const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
    if (aiOptOptions) {
      aiOptOptions.open = true;
    }
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

  const optimizePerfCheckbox = document.getElementById("optimize-performance") as HTMLInputElement | null;
  const optimizePerf = optimizePerfCheckbox?.checked ?? true;

  let prompt: string;
  if (optimizePerf) {
    prompt = optimizePerformancePrompt;
  } else {
    prompt = memoryEfficiencyPrompt;
  }

  // Just use big prompt maybe FIXME
  prompt = bigPrompt;

  switch (aiService) {
    case "openai": {
      console.log(prompt);
      const result = await sendPromptToOpenAI(prompt, apiKey);
      return extractCode(result);
    }
    case "anthropic": {
      console.log("Running " + aiService);
      console.log(prompt);
      const result = await sendPromptToAnthropic(prompt, apiKey);
      return extractCode(result);
    }
    case "gemini": {
      console.log("Running " + aiService);
      console.log(prompt);
      const result = await sendPromptToGemini(prompt, apiKey);
      return extractCode(result);
    }
    case "local": {
      console.log("Running " + aiService);
      console.log(prompt);
      const modelElement = document.getElementById("language-model-local") as HTMLSelectElement | null;
      const ipElement = document.getElementById("local-ip") as HTMLInputElement | null;
      const portElement = document.getElementById("local-port") as HTMLInputElement | null;

      const result = await sendPromptToOllama(
        prompt,
        modelElement?.value ?? "",
        ipElement?.value ?? "",
        portElement?.value ?? ""
      );
      if (result.includes("```")) {
        return extractPythonCodeBlock(result);
      } else {
        return result;
      }
    }
    case "amazon": {
      console.log("Running " + aiService);
      console.log(prompt);
      const result = await sendPromptToAmazon(prompt);
      return extractCode(result);
    }
    case "azure-openai": {
      console.log("Running " + aiService);
      console.log(prompt);
      const azureUrlElement = document.getElementById("azure-api-url") as HTMLInputElement | null;
      const azureCustomModelElement = document.getElementById("azure-custom-model") as HTMLInputElement | null;
      const azureModelSelectElement = document.getElementById("language-model-azure") as HTMLSelectElement | null;

      const azureOpenAiEndpoint = azureUrlElement?.value ?? "";
      const azureCustomModel = azureCustomModelElement?.value?.trim() || "";
      const azureOpenAiModel = azureCustomModel || azureModelSelectElement?.value || "gpt-5.2";
      const result = await sendPromptToAzureOpenAI(
        prompt,
        apiKey,
        azureOpenAiEndpoint,
        azureOpenAiModel
      );
      return extractCode(result);
    }
    default:
      return "";
  }
}

export function proposeOptimization(
  filename: string,
  file_number: number,
  line: LineData,
  params: OptimizationParams
): void {
  filename = unescape(filename);
  const useRegion = params["regions"];
  const prof = globalThis.profile;
  const this_file = prof.files[filename].lines;
  const imports = prof.files[filename].imports.join("\n");
  const start_region_line = this_file[line.lineno - 1]["start_region_line"];
  const end_region_line = this_file[line.lineno - 1]["end_region_line"];
  let context: string;
  const code_line = this_file[line.lineno - 1]["line"];
  let code_region: string;

  if (useRegion) {
    code_region = this_file
      .slice(start_region_line - 1, end_region_line)
      .map((e: LineData) => e["line"])
      .join("");
    context = this_file
      .slice(
        Math.max(0, start_region_line - 10),
        Math.min(start_region_line - 1, this_file.length)
      )
      .map((e: LineData) => e["line"])
      .join("");
  } else {
    code_region = code_line;
    context = this_file
      .slice(
        Math.max(0, line.lineno - 10),
        Math.min(line.lineno - 1, this_file.length)
      )
      .map((e: LineData) => e["line"])
      .join("");
  }

  // Count the number of leading spaces to match indentation level on output
  const leadingSpaceCount = countSpaces(code_line) + 3; // including the lightning bolt and explosion
  const indent =
    WhiteLightning + WhiteExplosion + "&nbsp;".repeat(leadingSpaceCount - 1);
  const elt = document.getElementById(`code-${file_number}-${line.lineno}`);

  (async () => {
    // TODO: check Amazon credentials
    const serviceSelect = document.getElementById("service-select") as HTMLSelectElement | null;
    const service = serviceSelect?.value ?? "";

    if (service === "openai") {
      const apiKeyElement = document.getElementById("api-key") as HTMLInputElement | null;
      const isValid = await isValidApiKey(apiKeyElement?.value ?? "");
      if (!isValid) {
        alert(
          "You must enter a valid OpenAI API key to activate proposed optimizations."
        );
        const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
        if (aiOptOptions) {
          aiOptOptions.open = true;
        }
        return;
      }
    }
    if (service === "anthropic") {
      const apiKeyElement = document.getElementById("anthropic-api-key") as HTMLInputElement | null;
      if (!apiKeyElement?.value) {
        alert(
          "You must enter an Anthropic API key to activate proposed optimizations."
        );
        const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
        if (aiOptOptions) {
          aiOptOptions.open = true;
        }
        return;
      }
    }
    if (service === "gemini") {
      const apiKeyElement = document.getElementById("gemini-api-key") as HTMLInputElement | null;
      if (!apiKeyElement?.value) {
        alert(
          "You must enter a Google Gemini API key to activate proposed optimizations."
        );
        const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
        if (aiOptOptions) {
          aiOptOptions.open = true;
        }
        return;
      }
    }
    if (service === "local") {
      const localModelsList = document.getElementById("local-models-list");
      if (localModelsList?.style.display === "none") {
        // No service was found.
        alert(
          "You must be connected to a running Ollama server to activate proposed optimizations."
        );
        const aiOptOptions = document.getElementById("ai-optimization-options") as HTMLDetailsElement | null;
        if (aiOptOptions) {
          aiOptOptions.open = true;
        }
        return;
      }
    }

    if (elt) {
      elt.innerHTML = `<em>${indent}working...</em>`;
    }

    let message = await optimizeCode(imports, code_region, line, context);
    if (!message) {
      if (elt) {
        elt.innerHTML = "";
      }
      return;
    }

    // Canonicalize newlines
    message = message.replace(/\r?\n/g, "\n");

    // Indent every line and format it
    const formattedCode = message
      .split("\n")
      .map(
        (line) =>
          indent + Prism.highlight(line, Prism.languages.python, "python")
      )
      .join("<br />");

    // Display the proposed optimization, with click-to-copy functionality.
    if (elt) {
      elt.innerHTML = `<hr><span title="click to copy" style="cursor: copy" id="opt-${file_number}-${line.lineno}">${formattedCode}</span>`;
    }

    const thisElt = document.getElementById(
      `opt-${file_number}-${line.lineno}`
    );

    if (thisElt) {
      thisElt.addEventListener("click", async (e) => {
        await copyOnClick(e, message);
        // After copying, briefly change the cursor back to the default to provide some visual feedback..
        (thisElt as HTMLElement).style.cursor = "auto";
        await new Promise((resolve) => setTimeout(resolve, 125));
        (thisElt as HTMLElement).style.cursor = "copy";
      });
    }
  })();
}
