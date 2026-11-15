import { isModelSelect, restoreModelSelection } from "./models";

// AI provider settings from `scalene config` (~/.scalene/config.json) and,
// with `scalene view --api-keys-from-env`, environment variables. These are
// never embedded in the HTML: the local server hands them to the page over
// a same-origin request.
export interface EnvApiKeys {
  openai?: string;
  openaiModel?: string;
  openaiUrl?: string;
  anthropic?: string;
  anthropicModel?: string;
  anthropicUrl?: string;
  gemini?: string;
  geminiModel?: string;
  geminiUrl?: string;
  azure?: string;
  azureUrl?: string;
  azureApiVersion?: string;
  azureModel?: string;
  awsAccessKey?: string;
  awsSecretKey?: string;
  awsRegion?: string;
  ollamaHost?: string;
  ollamaPort?: string;
  defaultProvider?: string;
}

let envApiKeys: EnvApiKeys = {};

export function getEnvApiKeys(): EnvApiKeys {
  return envApiKeys;
}

// Fetch saved and environment settings from the local server. Pages opened
// from a file (--html, --standalone) have no server, so skip the request.
export async function loadEnvApiKeys(): Promise<void> {
  if (!window.location.protocol.startsWith("http")) {
    return;
  }
  try {
    const response = await fetch("/env-api-keys.json", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null) {
      return;
    }
    const keys: EnvApiKeys = {};
    // defaultProvider picks the provider (see getDefaultProvider in
    // scalene-gui.ts) rather than filling a field.
    const fields = new Set<keyof EnvApiKeys>([...Object.values(envKeyMap), "defaultProvider"]);
    for (const field of fields) {
      const value = (data as Record<string, unknown>)[field];
      if (typeof value === "string" && value) {
        keys[field] = value;
      }
    }
    envApiKeys = keys;
  } catch {
    // No server or unreachable: leave the fields for the user to fill in.
  }
}

// Map element IDs to the settings that fill them when they're empty.
const envKeyMap: Record<string, keyof EnvApiKeys> = {
  "api-key": "openai",
  "openai-custom-model": "openaiModel",
  "openai-custom-url": "openaiUrl",
  "anthropic-api-key": "anthropic",
  "anthropic-custom-model": "anthropicModel",
  "anthropic-custom-url": "anthropicUrl",
  "gemini-api-key": "gemini",
  "gemini-custom-model": "geminiModel",
  "gemini-custom-url": "geminiUrl",
  "azure-api-key": "azure",
  "azure-api-url": "azureUrl",
  "azure-api-version": "azureApiVersion",
  "azure-custom-model": "azureModel",
  "aws-access-key": "awsAccessKey",
  "aws-secret-key": "awsSecretKey",
  "aws-region": "awsRegion",
  "local-ip": "ollamaHost",
  "local-port": "ollamaPort",
};

function restoreState(el: HTMLInputElement): void {
  const savedValue = localStorage.getItem(el.id);

  if (savedValue !== null && el instanceof HTMLSelectElement && isModelSelect(el)) {
    // Model choices can go stale as providers retire models.
    const restored = restoreModelSelection(el, savedValue);
    if (restored !== savedValue) {
      localStorage.setItem(el.id, restored);
    }
    return;
  }

  if (savedValue !== null) {
    switch (el.type) {
      case "checkbox":
      case "radio":
        el.checked = savedValue === "true";
        break;
      default:
        el.value = savedValue;
        break;
    }
  } else {
    // If no localStorage value, check for environment variable fallback
    const envKey = envKeyMap[el.id];
    const envValue = envKey ? envApiKeys[envKey] : undefined;
    if (envValue) {
      el.value = envValue;
    }
  }
}

// Fields in envKeyMap that aren't marked persistent (the OpenAI key) are
// never seen by restoreState, so prefill them here without saving them.
export function prefillNonPersistentEnvFields(): void {
  for (const [id, envKey] of Object.entries(envKeyMap)) {
    const el = document.getElementById(id) as HTMLInputElement | null;
    const envValue = envApiKeys[envKey];
    if (el && !el.classList.contains("persistent") && !el.value && envValue) {
      el.value = envValue;
    }
  }
}

function saveState(el: HTMLInputElement): void {
  el.addEventListener("change", () => {
    switch (el.type) {
      case "checkbox":
      case "radio":
        localStorage.setItem(el.id, String(el.checked));
        break;
      default:
        localStorage.setItem(el.id, el.value);
        break;
    }
  });
}

// Process all DOM elements in the class 'persistent', which saves their state in localStorage and restores them on load.
export function processPersistentElements(): void {
  const persistentElements = document.querySelectorAll<HTMLInputElement>(".persistent");

  // Restore state
  persistentElements.forEach((el) => {
    restoreState(el);
  });

  // Save state
  persistentElements.forEach((el) => {
    saveState(el);
  });
}

// Handle updating persistence when the DOM is updated.
export const observeDOM = (): void => {
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.addedNodes) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === 1) {
            const element = node as Element;
            if (element.matches && element.matches(".persistent")) {
              const inputElement = element as HTMLInputElement;
              restoreState(inputElement);
              inputElement.addEventListener("change", () => saveState(inputElement));
            }
          }
        });
      }
    });
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
};
