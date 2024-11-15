export async function sendPromptToAzureOpenAI(prompt, apiKey, apiUrl, aiModel) {
  const apiVersion = document.getElementById("azure-api-model-version").value;
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

  const data = await response.json();
  if (data.error) {
    if (
      data.error.code in
      {
        invalid_request_error: true,
        model_not_found: true,
        insufficient_quota: true,
      }
    ) {
      return "";
    }
  }
  try {
    console.log(
      `Debugging info: Retrieved ${JSON.stringify(data.choices[0], null, 4)}`,
    );
  } catch {
    console.log(
      `Debugging info: Failed to retrieve data.choices from the server. data = ${JSON.stringify(
        data,
      )}`,
    );
  }

  try {
    return data.choices[0].message.content.replace(/^\s*[\r\n]/gm, "");
  } catch {
    // return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
