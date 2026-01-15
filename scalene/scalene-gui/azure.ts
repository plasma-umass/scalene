interface AzureOpenAIChoice {
  message: {
    content: string;
  };
}

interface AzureOpenAIResponse {
  error?: {
    code?: string;
  };
  choices?: AzureOpenAIChoice[];
}

export async function sendPromptToAzureOpenAI(
  prompt: string,
  apiKey: string,
  apiUrl: string,
  aiModel: string
): Promise<string> {
  const apiVersionElement = document.getElementById("azure-api-version") as HTMLInputElement | null;
  const apiVersion = apiVersionElement?.value ?? "2024-02-15-preview";
  const endpoint = `${apiUrl}/openai/deployments/${aiModel}/chat/completions?api-version=${apiVersion}`;

  const body = JSON.stringify({
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
      "api-key": apiKey,
    },
    body: body,
  });

  const data: AzureOpenAIResponse = await response.json();
  if (data.error) {
    if (
      data.error.code &&
      data.error.code in {
        invalid_request_error: true,
        model_not_found: true,
        insufficient_quota: true,
      }
    ) {
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
