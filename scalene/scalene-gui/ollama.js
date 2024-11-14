export async function sendPromptToOllama(prompt, model, ipAddr, portNum) {
  const url = `http://${ipAddr}:${portNum}/api/chat`;
  const headers = { "Content-Type": "application/json" };
  const body = JSON.stringify({
    model: model,
    messages: [
      {
        role: "system",
        content:
          "You are an expert code assistant who only responds in Python code.", //You are a Python programming assistant who ONLY responds with blocks of commented, optimized code. You never respond with text. Just code, in a JSON object with the key "code".'
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    stream: false,
    //	format: "json",
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
      return {};
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
        const responseJson = JSON.parse(resp);
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
    return responseAggregated; // data.choices[0].message.content.replace(/^\s*[\r\n]/gm, "");
  } catch {
    // return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
    return "# Query failed. See JavaScript console (in Chrome: View > Developer > JavaScript Console) for more info.\n";
  }
}
