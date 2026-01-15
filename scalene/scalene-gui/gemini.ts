interface GeminiErrorResponse {
  error?: {
    code?: number;
    message?: string;
    status?: string;
  };
}

interface GeminiContentPart {
  text: string;
}

interface GeminiContent {
  parts: GeminiContentPart[];
  role: string;
}

interface GeminiCandidate {
  content: GeminiContent;
}

interface GeminiResponse extends GeminiErrorResponse {
  candidates?: GeminiCandidate[];
}

export async function sendPromptToGemini(
  prompt: string,
  apiKey: string
): Promise<string> {
  // Check for custom URL override (for Gemini-compatible servers)
  const customUrlElement = document.getElementById("gemini-custom-url") as HTMLInputElement | null;
  const customUrl = customUrlElement?.value?.trim() || "";

  // Check for custom model override
  const customModelElement = document.getElementById("gemini-custom-model") as HTMLInputElement | null;
  const customModel = customModelElement?.value?.trim() || "";
  const modelElement = document.getElementById("language-model-gemini") as HTMLSelectElement | null;
  const model = customModel || modelElement?.value || "gemini-2.0-flash";

  // Construct endpoint URL
  const baseUrl = customUrl || "https://generativelanguage.googleapis.com/v1beta";
  const endpoint = `${baseUrl}/models/${model}:generateContent?key=${apiKey}`;

  const body = JSON.stringify({
    contents: [
      {
        parts: [
          {
            text: prompt,
          },
        ],
      },
    ],
    systemInstruction: {
      parts: [
        {
          text: "You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, starting with ``` and ending with ```.",
        },
      ],
    },
    generationConfig: {
      temperature: 0.3,
      maxOutputTokens: 4096,
    },
  });

  console.log(body);

  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: body,
  });

  const data: GeminiResponse = await response.json();
  if (data.error) {
    console.error("Gemini API error:", data.error);
    if (data.error.status === "INVALID_ARGUMENT" || data.error.code === 400) {
      alert(`Gemini API error: ${data.error.message || "Invalid request"}`);
    } else if (data.error.status === "UNAUTHENTICATED" || data.error.code === 401) {
      alert("Invalid Gemini API key. Please check your API key and try again.");
    } else if (data.error.status === "RESOURCE_EXHAUSTED" || data.error.code === 429) {
      alert("Rate limit exceeded. Please wait a moment and try again.");
    } else {
      alert(`Gemini API error: ${data.error.message || "Unknown error"}`);
    }
    return "";
  }

  try {
    if (data.candidates && data.candidates[0] && data.candidates[0].content) {
      const text = data.candidates[0].content.parts
        .map((part) => part.text)
        .join("");
      console.log(
        `Debugging info: Retrieved ${JSON.stringify(data.candidates[0], null, 4)}`
      );
      return text.replace(/^\s*[\r\n]/gm, "");
    }
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  } catch {
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
