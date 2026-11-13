import { ModelNotFoundError } from "./models";

interface AnthropicErrorResponse {
  error?: {
    type?: string;
    message?: string;
  };
}

interface AnthropicContentBlock {
  type: string;
  text?: string;
}

interface AnthropicResponse extends AnthropicErrorResponse {
  content?: AnthropicContentBlock[];
}

interface AnthropicModelInfo {
  id: string;
  created_at?: string;
}

interface AnthropicModelsResponse extends AnthropicErrorResponse {
  data?: AnthropicModelInfo[];
}

const ANTHROPIC_API_BASE = "https://api.anthropic.com/v1";

function anthropicHeaders(apiKey: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "x-api-key": apiKey,
    "anthropic-version": "2023-06-01",
    "anthropic-dangerous-direct-browser-access": "true",
  };
}

function customMessagesUrl(): string {
  const el = document.getElementById("anthropic-custom-url") as HTMLInputElement | null;
  return el?.value?.trim() || "";
}

export async function sendPromptToAnthropic(
  prompt: string,
  apiKey: string,
  model: string
): Promise<string> {
  // A custom URL points at an Anthropic-compatible messages endpoint.
  const endpoint = customMessagesUrl() || `${ANTHROPIC_API_BASE}/messages`;

  const body = JSON.stringify({
    model: model,
    // Current models think before answering by default, and thinking counts
    // toward max_tokens, so leave room for both.
    max_tokens: 16000,
    messages: [
      {
        role: "user",
        content: prompt,
      },
    ],
    system:
      "You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, starting with ``` and ending with ```.",
  });

  console.log(body);

  const response = await fetch(endpoint, {
    method: "POST",
    headers: anthropicHeaders(apiKey),
    body: body,
  });

  const data: AnthropicResponse = await response.json();
  if (data.error) {
    console.error("Anthropic API error:", data.error);
    if (data.error.type === "not_found_error") {
      throw new ModelNotFoundError("anthropic", model, data.error.message || "not found");
    }
    if (data.error.type === "authentication_error") {
      alert("Invalid Anthropic API key. Please check your API key and try again.");
    } else if (data.error.type === "rate_limit_error") {
      alert("Rate limit exceeded. Please wait a moment and try again.");
    } else {
      alert(`Anthropic API error: ${data.error.message || "Unknown error"}`);
    }
    return "";
  }

  // The response may begin with thinking blocks; the answer is in the text
  // blocks.
  const text = (data.content ?? [])
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("");
  if (text) {
    console.log(`Debugging info: Retrieved ${JSON.stringify(data.content, null, 4)}`);
    return text.replace(/^\s*[\r\n]/gm, "");
  }
  console.log(`Debugging info: no text in response ${JSON.stringify(data)}`);
  return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
}

// Fetch the models available to this API key, newest first (the order the
// API returns them in).
export async function fetchAnthropicModels(apiKey: string): Promise<string[]> {
  if (!apiKey) return [];

  const customUrl = customMessagesUrl();
  const endpoint = customUrl
    ? customUrl.replace(/\/messages\/?$/, "/models")
    : `${ANTHROPIC_API_BASE}/models`;

  try {
    const response = await fetch(`${endpoint}?limit=1000`, {
      method: "GET",
      headers: anthropicHeaders(apiKey),
    });
    const data: AnthropicModelsResponse = await response.json();
    if (data.error || !data.data) {
      console.error("Failed to fetch Anthropic models:", data.error);
      return [];
    }
    return data.data.map((m) => m.id);
  } catch (error) {
    console.error("Error fetching Anthropic models:", error);
    return [];
  }
}
