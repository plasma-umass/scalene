import {
  BedrockRuntimeClient,
  InvokeModelCommand,
} from "@aws-sdk/client-bedrock-runtime";
import { ModelNotFoundError } from "./models";

interface AnthropicResponse {
  content: Array<{ type: string; text?: string }>;
}

interface OpenAIStyleResponse {
  choices: Array<{
    message: {
      content: string;
    };
  }>;
}

export async function sendPromptToAmazon(prompt: string, modelId: string): Promise<string> {
  const accessKeyIdElement = document.getElementById("aws-access-key") as HTMLInputElement | null;
  const secretAccessKeyElement = document.getElementById("aws-secret-key") as HTMLInputElement | null;
  const regionElement = document.getElementById("aws-region") as HTMLInputElement | null;

  const accessKeyId =
    accessKeyIdElement?.value ||
    localStorage.getItem("aws-access-key") ||
    "";
  const secretAccessKey =
    secretAccessKeyElement?.value ||
    localStorage.getItem("aws-secret-key") ||
    "";
  const region =
    regionElement?.value ||
    localStorage.getItem("aws-region") ||
    "us-east-1";

  // Configure AWS Credentials
  const credentials = {
    accessKeyId: accessKeyId,
    secretAccessKey: secretAccessKey,
  };

  // Initialize the Bedrock Runtime Client
  const client = new BedrockRuntimeClient({
    region: region,
    credentials: credentials,
  });

  let body: Record<string, unknown> = {};
  // Enough for a code suggestion, and within every model's output limit
  // (Haiku 4.5 and Opus 4.5 reject more than 64000).
  const max_tokens = 16000;

  // Claude model IDs look like anthropic.claude-..., optionally with an
  // inference-profile prefix (us., global., ...).
  const isClaude = /(^|\.)anthropic\./.test(modelId);

  if (isClaude) {
    body = {
      anthropic_version: "bedrock-2023-05-31",
      max_tokens: max_tokens,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "text",
              text: prompt,
            },
          ],
        },
      ],
    };
  } else {
    body = {
      max_completion_tokens: max_tokens,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "text",
              text: prompt,
            },
          ],
        },
      ],
    };
  }

  const params = {
    modelId: modelId,
    body: JSON.stringify(body),
  };

  try {
    const command = new InvokeModelCommand(params);
    const response = await client.send(command);

    // Convert the response body to text
    const responseBlob = new Blob([response.body as BlobPart]);
    const responseText = await responseBlob.text();
    const parsedResponse = JSON.parse(responseText);
    console.log("parsedResponse = " + responseText);

    if (isClaude) {
      // Skip any thinking blocks that precede the answer.
      const anthropicResponse = parsedResponse as AnthropicResponse;
      const responseContents = anthropicResponse.content
        .filter((block) => block.type === "text" && typeof block.text === "string")
        .map((block) => block.text)
        .join("");
      return responseContents.trim();
    } else {
      const openaiResponse = parsedResponse as OpenAIStyleResponse;
      const responseContents = openaiResponse.choices[0].message.content.replace(
        /<reasoning>[\s\S]*?<\/reasoning>/g,
        ""
      );
      return responseContents.trim();
    }
  } catch (err) {
    const error = err as Error;
    console.error(err);
    // How Bedrock refuses a model: unknown ID, retired ("Legacy") model, or
    // one this account isn't allowed to use.
    if (
      error.name === "ResourceNotFoundException" ||
      (error.name === "ValidationException" && /model identifier is invalid/i.test(error.message)) ||
      (error.name === "AccessDeniedException" && /not available for this account/i.test(error.message))
    ) {
      throw new ModelNotFoundError("amazon", modelId, error.message);
    }
    return `# Error: ${error.message}`;
  }
}
