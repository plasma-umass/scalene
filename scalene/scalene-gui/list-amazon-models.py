import boto3

client = boto3.client("bedrock")
response = client.list_foundation_models()
for model_summary in response["modelSummaries"]:
    print(
        f"Model ID: {model_summary['modelId']}, Provider: {model_summary['providerName']}"
    )
