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
  rankReplacements,
  resolveModel,
  setSelectedModel,
} from "./models";

// Models to choose a replacement from. For Bedrock this is our curated list:
// Bedrock's listing API reports models as ACTIVE even when the account isn't
// allowed to call them, so it can't tell us what will work.
async function listAvailableModels(provider: ModelProvider, apiKey: string): Promise<string[]> {
  switch (provider) {
    case "anthropic":
      return fetchAnthropicModels(apiKey);
    case "openai":
      return fetchOpenAIModels(apiKey);
    case "gemini":
      return fetchGeminiModels(apiKey);
    case "amazon":
      return MODEL_REGISTRY.amazon.models.map((m) => m.id);
    default:
      return [];
  }
}

// How many replacements to try before giving up.
const MAX_REPLACEMENTS = 2;

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
    const candidates = rankReplacements(model, available, MODEL_REGISTRY[provider].defaultModel).slice(
      0,
      MAX_REPLACEMENTS
    );
    if (candidates.length === 0) {
      alert(`${err.message}\n\nPlease choose a different model.`);
      return "";
    }
    for (const replacement of candidates) {
      console.warn(`Retrying with ${replacement} in place of ${model}.`);
      try {
        const result = await send(replacement);
        if (!result) {
          // The replacement exists but the request failed for another reason
          // (rate limit, overload, ...), which the provider has already
          // reported. Don't adopt a model we haven't seen work.
          return result;
        }
        setSelectedModel(provider, replacement);
        alert(`The model "${model}" is not available, so Scalene switched to "${replacement}".`);
        return result;
      } catch (retryErr) {
        if (!(retryErr instanceof ModelNotFoundError)) throw retryErr;
        console.warn(retryErr.message);
      }
    }
    alert(`${err.message}\n\nScalene also tried ${candidates.join(", ")}. Please choose a different model.`);
    return "";
  }
}
