# TypeScript Conversion Plan for Scalene GUI

## Overview

Converting the Scalene GUI JavaScript files to TypeScript for improved type safety, better IDE support, and easier maintenance.

## Build Configuration

- **Bundler**: esbuild (fast, simple, no webpack overhead)
- **Type Checker**: TypeScript compiler (tsc --noEmit)
- **Target**: ES2020
- **Module System**: ESNext with bundler resolution

### package.json Scripts

```json
{
  "scripts": {
    "build": "esbuild scalene-gui.ts --bundle --minify --sourcemap --target=es2020 --outfile=scalene-gui-bundle.js",
    "build:dev": "esbuild scalene-gui.ts --bundle --sourcemap --target=es2020 --outfile=scalene-gui-bundle.js",
    "watch": "esbuild scalene-gui.ts --bundle --sourcemap --target=es2020 --outfile=scalene-gui-bundle.js --watch",
    "typecheck": "tsc --noEmit"
  }
}
```

## Conversion Status

### Completed

- [x] `utils.ts` - Utility functions (escapeHTML, extractCode, makeTextRecursivelySelectable)
- [x] `openai.ts` - OpenAI API integration with proper interfaces
- [x] `ollama.ts` - Ollama local LLM integration
- [x] `amazon.ts` - AWS Bedrock integration (Anthropic and OpenAI-style responses)
- [x] `azure.ts` - Azure OpenAI integration
- [x] `persistence.ts` - LocalStorage state persistence
- [x] `gui-elements.ts` - Vega-Lite chart builders with LineProfile/FileProfile interfaces
- [x] `optimizations.ts` - AI optimization request handling
- [x] `scalene-gui.ts` - Main entry point (largest file, imports all others)
- [x] `scalene-demo.ts` - Demo functionality
- [x] `scalene-fetch.ts` - Profile fetching utilities
- [x] `prism.d.ts` - Type declarations for Prism.js
- [x] `tablesort.d.ts` - Type declarations for Tablesort.js

### External Libraries (Kept as JS with type declarations)

- `prism.js` - Syntax highlighting (external library, with prism.d.ts declarations)
- `tablesort.js` - Table sorting (external library, with tablesort.d.ts declarations)

## Type Definitions Added

### Interfaces

- `OpenAIChoice`, `OpenAIResponse` - OpenAI API responses
- `OllamaModel`, `OllamaTagsResponse`, `OllamaMessage`, `OllamaResponse` - Ollama API
- `AnthropicResponse`, `OpenAIStyleResponse` - Amazon Bedrock responses
- `AzureOpenAIChoice`, `AzureOpenAIResponse` - Azure API responses
- `LineProfile`, `FileProfile`, `ChartParams` - Profile data structures for Vega-Lite charts
- `LineData`, `FunctionData`, `FileData`, `Profile` - Main profile data types
- `Column`, `TableParams`, `OptimizationParams` - GUI-specific types

### DOM Element Types

All DOM element access uses proper type assertions:
```typescript
const element = document.getElementById("my-id") as HTMLInputElement | null;
```

## Dependencies

```json
{
  "devDependencies": {
    "@types/node": "^20.10.0",
    "@types/prismjs": "^1.26.0",
    "esbuild": "^0.24.0",
    "typescript": "^5.3.3"
  },
  "dependencies": {
    "@aws-sdk/client-bedrock-runtime": "^3.729.0",
    "buffer": "^6.0.3",
    "vega": "^5.30.0",
    "vega-embed": "^6.28.0",
    "vega-lite": "^5.21.0"
  }
}
```

## Build Steps

1. Install dependencies: `npm install`
2. Type check: `npm run typecheck`
3. Build bundle: `npm run build`
4. Development build (unminified): `npm run build:dev`
5. Watch mode: `npm run watch`

## Notes

- Using `strictNullChecks: true` for better null safety
- All external API responses have explicit interface definitions
- DOM element access uses null-safe patterns with optional chaining
- External JS libraries (`prism.js`, `tablesort.js`) kept as-is with `.d.ts` declaration files
- Window functions exposed globally for HTML onclick handlers
- Build produces ~1.1MB minified bundle with source maps

## Migration Complete

All JavaScript files have been successfully converted to TypeScript. The original `.js` files can be removed once the TypeScript version is verified in production.
