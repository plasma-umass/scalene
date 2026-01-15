import {
  BedrockRuntimeClient,
  InvokeModelCommand,
} from "@aws-sdk/client-bedrock-runtime";

interface AnthropicResponse {
  content: Array<{ text: string }>;
}

interface OpenAIStyleResponse {
  choices: Array<{
    message: {
      content: string;
    };
  }>;
}

export async function sendPromptToAmazon(prompt: string): Promise<string> {
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
  const max_tokens = 65536; // arbitrary large number

  const modelElement = document.getElementById("language-model-amazon") as HTMLSelectElement | null;
  const modelId = modelElement?.value ?? "";

  if (modelId.startsWith("us.anthropic")) {
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

    if (modelId.startsWith("us.anthropic")) {
      const anthropicResponse = parsedResponse as AnthropicResponse;
      const responseContents = anthropicResponse.content[0].text;
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
    return `# Error: ${error.message}`;
  }
}
