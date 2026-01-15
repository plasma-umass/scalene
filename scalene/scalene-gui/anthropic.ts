interface AnthropicErrorResponse {
  error?: {
    type?: string;
    message?: string;
  };
}

interface AnthropicContentBlock {
  type: string;
  text: string;
}

interface AnthropicResponse extends AnthropicErrorResponse {
  content?: AnthropicContentBlock[];
}

export async function sendPromptToAnthropic(
  prompt: string,
  apiKey: string
): Promise<string> {
  // Check for custom URL override (for Anthropic-compatible servers)
  const customUrlElement = document.getElementById("anthropic-custom-url") as HTMLInputElement | null;
  const customUrl = customUrlElement?.value?.trim() || "";
  const endpoint = customUrl || "https://api.anthropic.com/v1/messages";

  // Check for custom model override
  const customModelElement = document.getElementById("anthropic-custom-model") as HTMLInputElement | null;
  const customModel = customModelElement?.value?.trim() || "";
  const modelElement = document.getElementById("language-model-anthropic") as HTMLSelectElement | null;
  const model = customModel || modelElement?.value || "claude-sonnet-4-5-20250929";

  const body = JSON.stringify({
    model: model,
    max_tokens: 4096,
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
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: body,
  });

  const data: AnthropicResponse = await response.json();
  if (data.error) {
    console.error("Anthropic API error:", data.error);
    if (data.error.type === "authentication_error") {
      alert("Invalid Anthropic API key. Please check your API key and try again.");
    } else if (data.error.type === "rate_limit_error") {
      alert("Rate limit exceeded. Please wait a moment and try again.");
    } else {
      alert(`Anthropic API error: ${data.error.message || "Unknown error"}`);
    }
    return "";
  }

  try {
    if (data.content && data.content[0]) {
      console.log(
        `Debugging info: Retrieved ${JSON.stringify(data.content[0], null, 4)}`
      );
      return data.content[0].text.replace(/^\s*[\r\n]/gm, "");
    }
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  } catch {
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
