function restoreState(el) {
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
  }
}

function saveState(el) {
  el.addEventListener("change", () => {
    switch (el.type) {
      case "checkbox":
      case "radio":
        localStorage.setItem(el.id, el.checked);
        break;
      default:
        localStorage.setItem(el.id, el.value);
        break;
    }
  });
}

// Process all DOM elements in the class 'persistent', which saves their state in localStorage and restores them on load.
export function processPersistentElements() {
  const persistentElements = document.querySelectorAll(".persistent");

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
export const observeDOM = () => {
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.addedNodes) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.matches(".persistent")) {
            restoreState(node);
            node.addEventListener("change", () => saveState(node));
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
