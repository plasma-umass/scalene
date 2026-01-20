// Declare envApiKeys as a global variable that may be injected by the template
declare const envApiKeys: {
  openai?: string;
  anthropic?: string;
  gemini?: string;
  azure?: string;
  azureUrl?: string;
  awsAccessKey?: string;
  awsSecretKey?: string;
  awsRegion?: string;
} | undefined;

// Map element IDs to their corresponding environment variable keys
const envKeyMap: Record<string, keyof NonNullable<typeof envApiKeys>> = {
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
    if (envKey && typeof envApiKeys !== "undefined" && envApiKeys[envKey]) {
      el.value = envApiKeys[envKey] as string;
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
