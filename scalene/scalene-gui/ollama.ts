interface OllamaModel {
  name: string;
}

interface OllamaTagsResponse {
  models: OllamaModel[];
}

interface OllamaMessage {
  content?: string;
}

interface OllamaResponse {
  message?: OllamaMessage;
  done?: boolean;
}

export async function fetchModelNames(
  local_ip: string,
  local_port: string,
  revealInstallMessage: () => void
): Promise<string[]> {
  try {
    const response = await fetch(`http://${local_ip}:${local_port}/api/tags`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data: OllamaTagsResponse = await response.json();

    // Extracting the model names
    const modelNames = data.models.map((model) => model.name);
    if (modelNames.length === 0) {
      revealInstallMessage();
    }
    return modelNames;
  } catch (error) {
    console.error("Error fetching model names:", error);
    revealInstallMessage();
    return [];
  }
}

export async function sendPromptToOllama(
  prompt: string,
  model: string,
  ipAddr: string,
  portNum: string
): Promise<string> {
  const url = `http://${ipAddr}:${portNum}/api/chat`;
  const headers = { "Content-Type": "application/json" };
  const body = JSON.stringify({
    model: model,
    messages: [
      {
        role: "system",
        content:
          "You are an expert code assistant who only responds in Python code.",
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    stream: false,
    temperature: 0.3,
    frequency_penalty: 0,
    presence_penalty: 0,
    user: "scalene-user",
  });

  console.log(body);

  let done = false;
  let responseAggregated = "";
  let retried = 0;
  const retries = 3;

  while (!done) {
    if (retried >= retries) {
      return "";
    }

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: headers,
        body: body,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const text = await response.text();
      const responses = text.split("\n");
      for (const resp of responses) {
        if (!resp.trim()) continue;
        const responseJson: OllamaResponse = JSON.parse(resp);
        if (responseJson.message && responseJson.message.content) {
          responseAggregated += responseJson.message.content;
        }

        if (responseJson.done) {
          done = true;
          break;
        }
      }
    } catch (error) {
      console.log(`Error: ${error}`);
      retried++;
    }
  }

  console.log(responseAggregated);
  try {
    return responseAggregated;
  } catch {
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
