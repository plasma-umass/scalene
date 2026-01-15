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
  const endpoint = "https://api.openai.com/v1/chat/completions";
  const modelElement = document.getElementById("language-model-openai") as HTMLSelectElement | null;
  const model = modelElement?.value ?? "gpt-4";

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
