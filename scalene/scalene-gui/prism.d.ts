// Type declarations for prism.js
export const Prism: {
  highlight: (code: string, grammar: unknown, language: string) => string;
  languages: {
    python: unknown;
    [key: string]: unknown;
  };
};

export default Prism;
