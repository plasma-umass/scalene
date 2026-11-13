import { ModelNotFoundError } from "./models";

interface OpenAIErrorResponse {
  error?: {
    code?: string;
    message?: string;
  };
}

interface OpenAIChoice {
  message: {
    content: string;
  };
}

interface OpenAIResponse extends OpenAIErrorResponse {
  choices?: OpenAIChoice[];
}

interface OpenAIModel {
  id: string;
  owned_by: string;
}

interface OpenAIModelsResponse extends OpenAIErrorResponse {
  data?: OpenAIModel[];
}

async function tryApi(apiKey: string): Promise<Response> {
  const response = await fetch("https://api.openai.com/v1/completions", {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
  });
  return response;
}

export async function isValidApiKey(apiKey: string): Promise<boolean> {
  const response = await tryApi(apiKey);
  const data: OpenAIErrorResponse = await response.json();
  if (
    data.error &&
    data.error.code &&
    data.error.code in {
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

// Fetch available models from OpenAI API
export async function fetchOpenAIModels(apiKey: string): Promise<string[]> {
  if (!apiKey) return [];

  // Check for custom URL
  const customUrlElement = document.getElementById("openai-custom-url") as HTMLInputElement | null;
  const customUrl = customUrlElement?.value?.trim() || "";
  const baseUrl = customUrl || "https://api.openai.com/v1";
  const endpoint = `${baseUrl}/models`;

  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${apiKey}`,
      },
    });

    const data: OpenAIModelsResponse = await response.json();
    if (data.error || !data.data) {
      console.error("Failed to fetch OpenAI models:", data.error);
      return [];
    }

    // Filter for chat models and sort alphabetically
    const chatModels = data.data
      .map((m) => m.id)
      .filter((id) =>
        id.includes("gpt") ||
        id.includes("o1") ||
        id.includes("o3") ||
        id.includes("o4")
      )
      .filter((id) => !id.includes("instruct") && !id.includes("realtime") && !id.includes("audio"))
      .sort();

    return chatModels;
  } catch (error) {
    console.error("Error fetching OpenAI models:", error);
    return [];
  }
}

export function checkApiKey(apiKey: string): void {
  (async () => {
    try {
      window.localStorage.setItem("scalene-api-key", apiKey);
    } catch {
      // Do nothing if key not found
    }
    // If the API key is empty, clear the status indicator.
    if (apiKey.length === 0) {
      const validKeyElement = document.getElementById("valid-api-key");
      if (validKeyElement) {
        validKeyElement.innerHTML = "";
      }
      return;
    }
    // Skip validation if using a custom URL (OpenAI-compatible servers may not have the same validation endpoint)
    const customUrlElement = document.getElementById("openai-custom-url") as HTMLInputElement | null;
    const customUrl = customUrlElement?.value?.trim() || "";
    if (customUrl) {
      const validKeyElement = document.getElementById("valid-api-key");
      if (validKeyElement) {
        validKeyElement.innerHTML = ""; // Don't show validation for custom endpoints
      }
      return;
    }
    const isValid = await isValidApiKey(apiKey);
    const validKeyElement = document.getElementById("valid-api-key");
    if (validKeyElement) {
      if (!isValid) {
        validKeyElement.innerHTML = "&#10005;";
      } else {
        validKeyElement.innerHTML = "&check;";
      }
    }
  })();
}

const SYSTEM_PROMPT =
  "You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, starting with ``` and ending with ```.";

const QUERY_FAILED =
  "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";

// The Responses API's reply: a list of output items, of which "message" items
// hold the text (reasoning models also emit "reasoning" items).
interface OpenAIResponsesReply extends OpenAIErrorResponse {
  status?: string;
  output?: {
    type: string;
    content?: { type: string; text?: string; refusal?: string }[];
  }[];
}

// Returns true if the error was reported (and the caller should give up);
// throws ModelNotFoundError so the caller can recover.
function reportError(data: OpenAIErrorResponse, model: string): boolean {
  if (!data.error) return false;
  console.error("OpenAI API error:", data.error);
  if (data.error.code === "model_not_found") {
    throw new ModelNotFoundError("openai", model, data.error.message || "not found");
  }
  if (data.error.code === "insufficient_quota") {
    alert("You need to add funds to your OpenAI account to use this feature.");
  } else {
    alert(`OpenAI API error: ${data.error.message || data.error.code || "Unknown error"}`);
  }
  return true;
}

export async function sendPromptToOpenAI(
  prompt: string,
  apiKey: string,
  model: string
): Promise<string> {
  // A custom URL means an OpenAI-compatible server (vLLM, Cohere, ...), which
  // speaks Chat Completions. OpenAI itself gets the Responses API, the only
  // one that serves every current model (the -pro models reject Chat
  // Completions).
  const customUrlElement = document.getElementById("openai-custom-url") as HTMLInputElement | null;
  const customUrl = customUrlElement?.value?.trim() || "";
  const text = customUrl
    ? await sendChatCompletion(customUrl, prompt, apiKey, model)
    : await sendResponse(prompt, apiKey, model);
  return text === null ? "" : text.replace(/^\s*[\r\n]/gm, "");
}

async function post(endpoint: string, apiKey: string, body: object): Promise<unknown> {
  const json = JSON.stringify(body);
  console.log(json);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: json,
  });
  return response.json();
}

// Returns the reply text, or null if an error was already reported.
async function sendResponse(prompt: string, apiKey: string, model: string): Promise<string | null> {
  const data = (await post("https://api.openai.com/v1/responses", apiKey, {
    model: model,
    instructions: SYSTEM_PROMPT,
    input: prompt,
    safety_identifier: "scalene-user",
    store: false,
  })) as OpenAIResponsesReply;
  if (reportError(data, model)) return null;
  console.log(`Debugging info: Retrieved ${JSON.stringify(data.output, null, 4)}`);
  const parts = (data.output ?? [])
    .filter((item) => item.type === "message")
    .flatMap((item) => item.content ?? []);
  const text = parts
    .filter((part) => part.type === "output_text")
    .map((part) => part.text ?? "")
    .join("");
  if (text) return text;
  const refusal = parts.find((part) => part.type === "refusal")?.refusal;
  if (refusal) return `# ${refusal}\n`;
  return QUERY_FAILED;
}

async function sendChatCompletion(
  endpoint: string,
  prompt: string,
  apiKey: string,
  model: string
): Promise<string | null> {
  const data = (await post(endpoint, apiKey, {
    model: model,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: prompt },
    ],
    user: "scalene-user",
  })) as OpenAIResponse;
  if (reportError(data, model)) return null;
  console.log(`Debugging info: Retrieved ${JSON.stringify(data.choices?.[0], null, 4)}`);
  return data.choices?.[0]?.message?.content ?? QUERY_FAILED;
}
