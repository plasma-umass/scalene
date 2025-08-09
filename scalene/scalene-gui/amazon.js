import {
  BedrockRuntimeClient,
  InvokeModelCommand,
} from "@aws-sdk/client-bedrock-runtime";

export async function sendPromptToAmazon(prompt) {
  const accessKeyId =
    document.getElementById("aws-access-key").value ||
    localStorage.getItem("aws-access-key");
  const secretAccessKey =
    document.getElementById("aws-secret-key").value ||
    localStorage.getItem("aws-secret-key");
  const region =
    document.getElementById("aws-region").value ||
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

    let body = {};
    const max_tokens = 65536; // arbitrary large number

    const modelId = document.getElementById("language-model-amazon").value;
    
    if (modelId.startsWith('us.anthropic')) {
	body = {
	    "anthropic_version": "bedrock-2023-05-31", 
	    "max_tokens": max_tokens,
	    "messages": [
		{
		    "role": "user",
		    "content": [
			{
			    "type": "text",
			    "text": prompt
			}
		    ]
		}
	    ]
	};
    } else {
	body = {
	    "max_completion_tokens": max_tokens,
	    "messages": [
		{
		    "role": "user",
		    "content": [
			{
			    "type": "text",
			    "text": prompt
			}
		    ]
		}
	    ]
	};
    }
    
    const params = {
	"modelId": modelId,
	"body": JSON.stringify(body)
    }

  try {
    const command = new InvokeModelCommand(params);
    const response = await client.send(command);

    // Convert the response body to text
    const responseBlob = new Blob([response.body]);
    const responseText = await responseBlob.text();
      const parsedResponse = JSON.parse(responseText);
      console.log("parsedResponse = " + responseText);
    const responseContents = parsedResponse.content[0].text;

    return responseContents.trim();
  } catch (err) {
    console.error(err);
    return `# Error: ${err.message}`;
  }
}
