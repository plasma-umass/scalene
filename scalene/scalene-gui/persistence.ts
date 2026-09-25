// AI provider credentials taken from environment variables. These are
// never embedded in the HTML: with `scalene view --api-keys-from-env`, the
// local server hands them to the page over a same-origin request.
export interface EnvApiKeys {
  openai?: string;
  anthropic?: string;
  gemini?: string;
  azure?: string;
  azureUrl?: string;
  awsAccessKey?: string;
  awsSecretKey?: string;
  awsRegion?: string;
}

const envApiKeyFields: (keyof EnvApiKeys)[] = [
  "openai",
  "anthropic",
  "gemini",
  "azure",
  "azureUrl",
  "awsAccessKey",
  "awsSecretKey",
  "awsRegion",
];

let envApiKeys: EnvApiKeys = {};

export function getEnvApiKeys(): EnvApiKeys {
  return envApiKeys;
}

// Fetch environment credentials from the local server. The server returns
// an empty object unless --api-keys-from-env was given; pages opened from a
// file (--html, --standalone) have no server, so skip the request entirely.
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
    for (const field of envApiKeyFields) {
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

// Map element IDs to their corresponding environment variable keys
const envKeyMap: Record<string, keyof EnvApiKeys> = {
  "api-key": "openai",
  "anthropic-api-key": "anthropic",
  "gemini-api-key": "gemini",
  "azure-api-key": "azure",
  "azure-api-url": "azureUrl",
  "aws-access-key": "awsAccessKey",
  "aws-secret-key": "awsSecretKey",
  "aws-region": "awsRegion",
};

function restoreState(el: HTMLInputElement): void {
  const savedValue = localStorage.getItem(el.id);

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
