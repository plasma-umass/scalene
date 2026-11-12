// The single place where AI model IDs live.
//
// Providers retire model IDs regularly (e.g., #1123). To keep that from
// breaking the GUI:
//   * Every model ID the GUI knows about is defined here and nowhere else
//     (tests/test_model_registry.py enforces this).
//   * Defaults prefer aliases that providers move forward on their own.
//   * Saved selections of IDs known to be retired are migrated on load
//     (RETIRED_MODELS).
//   * When a provider rejects a model as unknown, the request is retried once
//     with a replacement picked from the provider's live model list (see
//     model-recovery.ts), and the saved selection is updated.

export type ModelProvider = "openai" | "anthropic" | "gemini" | "amazon" | "azure";

export interface ModelChoice {
  id: string;
  label: string;
}

interface ProviderModels {
  // ID of the <select> holding the model choice.
  selectId: string;
  // ID of the free-text "Custom model" override, if the provider has one.
  customModelId?: string;
  // Used when the select is empty and as the last-resort replacement.
  defaultModel: string;
  // Curated choices shown before the user refreshes from the provider.
  models: ModelChoice[];
}

export const MODEL_REGISTRY: Record<ModelProvider, ProviderModels> = {
  openai: {
    selectId: "language-model-openai",
    customModelId: "openai-custom-model",
    defaultModel: "gpt-5.2",
    models: [
      { id: "gpt-5.2", label: "GPT-5.2" },
      { id: "gpt-5.2-pro", label: "GPT-5.2 Pro" },
      { id: "gpt-5.1", label: "GPT-5.1" },
      { id: "gpt-5", label: "GPT-5" },
      { id: "gpt-5-mini", label: "GPT-5 mini" },
      { id: "gpt-5-nano", label: "GPT-5 nano" },
      { id: "gpt-4.1", label: "GPT-4.1" },
      { id: "gpt-4.1-mini", label: "GPT-4.1 mini" },
      { id: "gpt-4.1-nano", label: "GPT-4.1 nano" },
      { id: "o3-pro", label: "o3-pro" },
      { id: "o3", label: "o3" },
      { id: "o4-mini", label: "o4-mini" },
    ],
  },
  anthropic: {
    selectId: "language-model-anthropic",
    customModelId: "anthropic-custom-model",
    // Claude 5 model IDs are undated aliases.
    defaultModel: "claude-sonnet-5-5",
    models: [
      { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
      { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
      { id: "claude-haiku-5-5", label: "Claude Haiku 5.5" },
    ],
  },
  gemini: {
    selectId: "language-model-gemini",
    customModelId: "gemini-custom-model",
    // The *-latest aliases track Google's newest stable model of each tier.
    defaultModel: "gemini-pro-latest",
    models: [
      { id: "gemini-pro-latest", label: "Gemini Pro (latest)" },
      { id: "gemini-flash-latest", label: "Gemini Flash (latest)" },
      { id: "gemini-flash-lite-latest", label: "Gemini Flash Lite (latest)" },
      { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
      { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    ],
  },
  amazon: {
    selectId: "language-model-amazon",
    defaultModel: "anthropic.claude-sonnet-5-5",
    models: [
      { id: "anthropic.claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
      { id: "anthropic.claude-opus-5-5", label: "Claude Opus 5.5" },
      { id: "anthropic.claude-haiku-5-5", label: "Claude Haiku 5.5" },
    ],
  },
  azure: {
    // Azure takes deployment names, which usually match the model name.
    selectId: "language-model-azure",
    customModelId: "azure-custom-model",
    defaultModel: "gpt-4.1",
    models: [
      { id: "gpt-4.1", label: "GPT-4.1" },
      { id: "gpt-4.1-mini", label: "GPT-4.1 mini" },
      { id: "gpt-4o", label: "GPT-4o" },
      { id: "o3-mini", label: "o3-mini" },
    ],
  },
};

// Model IDs known to be retired (or never valid), mapped to their
// replacements. Saved selections are migrated on page load, before the
// provider ever sees them. This is a convenience: anything missing here is
// still caught at request time by model-recovery.ts.
export const RETIRED_MODELS: Record<string, string> = {
  // Retires 2026-11-30 (#1123).
  "claude-sonnet-4-5-20250929": "claude-sonnet-5-5",
  // These two IDs were never valid (the real snapshots are dated 20251101
  // and 20251001).
  "claude-opus-4-5-20251124": "claude-opus-5-5",
  "claude-haiku-4-5-20251015": "claude-haiku-5-5",
  "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "anthropic.claude-sonnet-5-5",
  "us.anthropic.claude-opus-4-5-20251124-v1:0": "anthropic.claude-opus-5-5",
  "us.anthropic.claude-haiku-4-5-20251015-v1:0": "anthropic.claude-haiku-5-5",
  // Preview and 2.0 models Google has retired or is retiring.
  "gemini-3-pro-preview": "gemini-pro-latest",
  "gemini-3-flash-preview": "gemini-flash-latest",
  "gemini-2.0-flash": "gemini-flash-latest",
  "gemini-2.0-flash-lite": "gemini-flash-lite-latest",
};

// (Plain fields rather than constructor parameter properties, so this file
// also runs under Node's type stripping in tests/test_model_registry.py.)
export class ModelNotFoundError extends Error {
  readonly provider: ModelProvider;
  readonly model: string;

  constructor(provider: ModelProvider, model: string, detail: string) {
    super(`Model "${model}" is not available: ${detail}`);
    this.name = "ModelNotFoundError";
    this.provider = provider;
    this.model = model;
  }
}

// --- Pure helpers (no DOM; unit-tested) ------------------------------------

// The model family: the ID minus version numbers, dates, and "latest", so that
// e.g. claude-sonnet-4-5-20250929 and claude-sonnet-5-5 are both
// "claude-sonnet", and gemini-2.0-flash and gemini-flash-latest are both
// "gemini-flash". Provider prefixes (us./global./anthropic.) are dropped.
export function modelFamily(id: string): string {
  const base = id
    .replace(/^(?:[a-z]{2,6}\.)?anthropic\./, "")
    .replace(/^models\//, "")
    .replace(/-v\d+(?::\d+)?$/, "");
  return base
    .split("-")
    .filter((part) => part !== "" && part !== "latest" && !/^\d/.test(part))
    .join("-");
}

function versionKey(id: string): number[] {
  return (id.match(/\d+/g) ?? []).map(Number);
}

// Positive if a is newer than b. "-latest" aliases outrank everything;
// otherwise compare version numbers left to right (so 5-5 > 4-6 > 4-5-2025...).
export function compareModelRecency(a: string, b: string): number {
  const aLatest = a.includes("latest") ? 1 : 0;
  const bLatest = b.includes("latest") ? 1 : 0;
  if (aLatest !== bLatest) return aLatest - bLatest;
  const ka = versionKey(a);
  const kb = versionKey(b);
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const diff = (ka[i] ?? -1) - (kb[i] ?? -1);
    if (diff !== 0) return diff;
  }
  return 0;
}

// Choose what to use in place of a model the provider rejected: the newest
// available model in the same family, else the registry default. Returns
// null if there is nothing different to try.
export function pickReplacement(
  failed: string,
  available: string[],
  defaultModel: string
): string | null {
  const family = modelFamily(failed);
  const candidates = available
    .filter((id) => id !== failed && modelFamily(id) === family)
    .sort((a, b) => compareModelRecency(b, a));
  if (candidates.length > 0) return candidates[0];
  if (available.length > 0 && !available.includes(defaultModel)) {
    // The provider told us what exists, and our default isn't in it.
    return null;
  }
  return defaultModel !== failed ? defaultModel : null;
}

// --- DOM helpers -------------------------------------------------------------

function getSelect(provider: ModelProvider): HTMLSelectElement | null {
  return document.getElementById(MODEL_REGISTRY[provider].selectId) as HTMLSelectElement | null;
}

function addOption(select: HTMLSelectElement, id: string, label: string): void {
  const option = document.createElement("option");
  option.value = id;
  option.textContent = label;
  select.appendChild(option);
}

// Fill each model <select> from the registry. Runs before persistent fields
// are restored, so saved selections apply on top.
export function populateModelSelects(): void {
  for (const provider of Object.keys(MODEL_REGISTRY) as ModelProvider[]) {
    const select = getSelect(provider);
    if (!select) continue;
    const { models, defaultModel } = MODEL_REGISTRY[provider];
    select.innerHTML = "";
    for (const { id, label } of models) {
      addOption(select, id, label);
    }
    select.value = defaultModel;
  }
}

// Called by persistence.ts when restoring a model <select>. Maps retired IDs
// forward, and keeps a saved model that isn't in the curated list (e.g. one
// picked after refreshing from the provider) rather than silently dropping it.
export function restoreModelSelection(select: HTMLSelectElement, saved: string): string {
  const value = RETIRED_MODELS[saved] ?? saved;
  if (value && !Array.from(select.options).some((o) => o.value === value)) {
    addOption(select, value, value);
  }
  select.value = value;
  return value;
}

export function isModelSelect(el: Element): boolean {
  return Object.values(MODEL_REGISTRY).some((p) => p.selectId === el.id);
}

export interface ResolvedModel {
  model: string;
  // "custom" models come from the free-text override; we never change those
  // automatically.
  source: "custom" | "select";
}

export function resolveModel(provider: ModelProvider): ResolvedModel {
  const { customModelId, defaultModel } = MODEL_REGISTRY[provider];
  if (customModelId) {
    const custom = (document.getElementById(customModelId) as HTMLInputElement | null)?.value?.trim();
    if (custom) return { model: custom, source: "custom" };
  }
  const selected = getSelect(provider)?.value;
  return { model: selected || defaultModel, source: "select" };
}

// Select `model` for `provider` (adding it as an option if needed) and save
// the choice, as if the user had picked it.
export function setSelectedModel(provider: ModelProvider, model: string): void {
  const select = getSelect(provider);
  if (!select) return;
  if (!Array.from(select.options).some((o) => o.value === model)) {
    addOption(select, model, model);
  }
  select.value = model;
  try {
    localStorage.setItem(select.id, model);
  } catch {
    // Storage may be unavailable; the in-page selection still applies.
  }
}

// Replace a model <select>'s options with a list fetched from the provider,
// keeping the current selection when it is still offered.
export function populateModelSelect(selectId: string, models: string[]): void {
  const select = document.getElementById(selectId) as HTMLSelectElement | null;
  if (!select || models.length === 0) return;
  const current = select.value;
  select.innerHTML = "";
  for (const id of models) {
    addOption(select, id, id);
  }
  if (models.includes(current)) {
    select.value = current;
  }
}
