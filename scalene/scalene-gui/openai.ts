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

export async function sendPromptToOpenAI(
  prompt: string,
  apiKey: string
): Promise<string> {
  // Check for custom URL override (for OpenAI-compatible servers like vLLM, Cohere)
  const customUrlElement = document.getElementById("openai-custom-url") as HTMLInputElement | null;
  const customUrl = customUrlElement?.value?.trim() || "";
  const endpoint = customUrl || "https://api.openai.com/v1/chat/completions";

  // Check for custom model override
  const customModelElement = document.getElementById("openai-custom-model") as HTMLInputElement | null;
  const customModel = customModelElement?.value?.trim() || "";
  const modelElement = document.getElementById("language-model-openai") as HTMLSelectElement | null;
  const model = customModel || modelElement?.value || "gpt-4";

  const body = JSON.stringify({
    model: model,
    messages: [
      {
        role: "system",
        content:
          "You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, starting with ``` and ending with ```.",
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    user: "scalene-user",
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

  const data: OpenAIResponse = await response.json();
  if (data.error) {
    if (
      data.error.code &&
      data.error.code in {
        invalid_request_error: true,
        model_not_found: true,
        insufficient_quota: true,
      }
    ) {
      if (data.error.code === "model_not_found" && model === "gpt-4") {
        // Technically, model_not_found applies only for GPT-4.0
        // if an account has not been funded with at least $1.
        alert(
          "You either need to add funds to your OpenAI account to use this feature, or you need to switch to GPT-3.5 if you are using free credits."
        );
      } else {
        alert(
          "You need to add funds to your OpenAI account to use this feature."
        );
      }
      return "";
    }
  }
  try {
    if (data.choices && data.choices[0]) {
      console.log(
        `Debugging info: Retrieved ${JSON.stringify(data.choices[0], null, 4)}`
      );
    }
  } catch {
    console.log(
      `Debugging info: Failed to retrieve data.choices from the server. data = ${JSON.stringify(data)}`
    );
  }

  try {
    if (data.choices && data.choices[0]) {
      return data.choices[0].message.content.replace(/^\s*[\r\n]/gm, "");
    }
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  } catch {
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
