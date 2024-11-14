export async function sendPromptToOpenAI(prompt, apiKey) {
  const endpoint = "https://api.openai.com/v1/chat/completions";
  const model = document.getElementById("language-model-openai").value;

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
      if (data.error.code === "model_not_found" && model === "gpt-4") {
        // Technically, model_not_found applies only for GPT-4.0
        // if an account has not been funded with at least $1.
        alert(
          "You either need to add funds to your OpenAI account to use this feature, or you need to switch to GPT-3.5 if you are using free credits.",
        );
      } else {
        alert(
          "You need to add funds to your OpenAI account to use this feature.",
        );
      }
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

