declare function loadDemo(): void;

const demoText = document.getElementById("demo-text");
if (demoText) {
  demoText.addEventListener("click", (e: Event) => {
    loadDemo();
    e.preventDefault();
  });
}
