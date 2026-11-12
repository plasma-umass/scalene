// Recovers from a provider rejecting a model as unknown, which is what
// happens when a model is retired: look up what the provider offers now, pick
// the closest replacement, retry once, and remember the new choice.

import { fetchAnthropicModels } from "./anthropic";
import { fetchGeminiModels } from "./gemini";
import { fetchOpenAIModels } from "./openai";
import {
  MODEL_REGISTRY,
  ModelNotFoundError,
  ModelProvider,
  pickReplacement,
  resolveModel,
  setSelectedModel,
} from "./models";

// Models the provider currently offers, or [] if we can't ask (Bedrock's
// listing API needs a separate client, and Azure lists deployments, not
// models).
async function listAvailableModels(provider: ModelProvider, apiKey: string): Promise<string[]> {
  switch (provider) {
    case "anthropic":
      return fetchAnthropicModels(apiKey);
    case "openai":
      return fetchOpenAIModels(apiKey);
    case "gemini":
      return fetchGeminiModels(apiKey);
    default:
      return [];
  }
}

export async function sendWithModelRecovery(
  provider: ModelProvider,
  apiKey: string,
  send: (model: string) => Promise<string>
): Promise<string> {
  const { model, source } = resolveModel(provider);
  try {
    return await send(model);
  } catch (err) {
    if (!(err instanceof ModelNotFoundError)) throw err;
    console.warn(err.message);
    if (source === "custom") {
      // Don't second-guess a model the user typed in.
      alert(`${err.message}\n\nCheck the "Custom model" field in the advanced options.`);
      return "";
    }
    const available = await listAvailableModels(provider, apiKey);
    const replacement = pickReplacement(model, available, MODEL_REGISTRY[provider].defaultModel);
    if (!replacement) {
      alert(`${err.message}\n\nPlease choose a different model.`);
      return "";
    }
    console.warn(`Retrying with ${replacement} in place of ${model}.`);
    try {
      const result = await send(replacement);
      setSelectedModel(provider, replacement);
      alert(`The model "${model}" is no longer available, so Scalene switched to "${replacement}".`);
      return result;
    } catch (retryErr) {
      if (retryErr instanceof ModelNotFoundError) {
        alert(`${err.message}\n\nThe replacement "${replacement}" was not available either. Please choose a different model.`);
        return "";
      }
      throw retryErr;
    }
  }
}
