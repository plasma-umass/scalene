#!/usr/bin/env node
// Checks the GUI's curated AI model IDs (scalene/scalene-gui/models.ts)
// against what each provider currently lists, and rewrites models.ts when a
// curated model has disappeared: the entry is replaced by (or merged into)
// its newest same-family successor, the default moves with it, and the old
// ID goes into RETIRED_MODELS so saved selections are migrated on load.
//
// Run by .github/workflows/update-models.yml, which opens a PR with the
// result. Locally (Node 22.6+):
//
//   node --experimental-strip-types scripts/update_models.mjs [--dry-run] [--report FILE]
//
// Providers are checked only when their credentials are set:
//   OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY (or GOOGLE_API_KEY),
//   AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_REGION, default us-east-1).
// Azure takes deployment names, which can't be checked centrally.
//
// The script never adds models on its own; newer models it notices are listed
// in the report for a human to consider.

import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GUI_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "scalene", "scalene-gui");
const MODELS_TS = join(GUI_DIR, "models.ts");

// Spacing between provider requests (provider APIs rate-limit bursts).
const REQUEST_GAP_MS = 2000;

// --- Fetching the live lists -------------------------------------------------

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let lastRequest = 0;

async function getJSON(url, headers) {
  for (let attempt = 0; ; attempt++) {
    const wait = lastRequest + REQUEST_GAP_MS - Date.now();
    if (wait > 0) await sleep(wait);
    lastRequest = Date.now();
    const response = await fetch(url, { headers });
    if ((response.status === 429 || response.status >= 500) && attempt < 3) {
      const retryAfter = Number(response.headers.get("retry-after"));
      await sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 10000 * (attempt + 1));
      continue;
    }
    if (!response.ok) {
      // Report only the error code: messages can echo part of the key, and
      // workflow logs on a public repo are public.
      let code = "";
      try {
        const body = await response.json();
        const error = body.error ?? body;
        code = error.code ?? error.type ?? error.status ?? "";
      } catch {
        // Not JSON; the status says enough.
      }
      throw new Error(`${new URL(url).host} returned ${response.status}${code ? ` (${code})` : ""}`);
    }
    return response.json();
  }
}

// Each returns [{ id, name? }] for the models the provider currently serves.
const LISTERS = {
  async openai(env) {
    if (!env.OPENAI_API_KEY) return null;
    const data = await getJSON("https://api.openai.com/v1/models", {
      Authorization: `Bearer ${env.OPENAI_API_KEY}`,
    });
    return data.data.map((m) => ({ id: m.id }));
  },

  async anthropic(env) {
    if (!env.ANTHROPIC_API_KEY) return null;
    const models = [];
    let after = "";
    do {
      const data = await getJSON(`https://api.anthropic.com/v1/models?limit=1000${after}`, {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      });
      models.push(...data.data.map((m) => ({ id: m.id, name: m.display_name })));
      after = data.has_more ? `&after_id=${encodeURIComponent(data.last_id)}` : "";
    } while (after);
    return models;
  },

  async gemini(env) {
    const key = env.GEMINI_API_KEY || env.GOOGLE_API_KEY;
    if (!key) return null;
    const models = [];
    let pageToken = "";
    do {
      const data = await getJSON(
        `https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000${pageToken}`,
        { "x-goog-api-key": key }
      );
      for (const m of data.models ?? []) {
        if (m.supportedGenerationMethods?.includes("generateContent")) {
          models.push({ id: m.name.replace(/^models\//, ""), name: m.displayName });
        }
      }
      pageToken = data.nextPageToken ? `&pageToken=${encodeURIComponent(data.nextPageToken)}` : "";
    } while (pageToken);
    return models;
  },

  // Bedrock: the system-defined inference profiles, which is what the GUI
  // invokes. (Being listed doesn't mean a given account may call a model;
  // the GUI recovers from that at request time.)
  async amazon(env) {
    if (!env.AWS_ACCESS_KEY_ID || !env.AWS_SECRET_ACCESS_KEY) return null;
    const require = createRequire(join(GUI_DIR, "package.json"));
    const { BedrockClient, ListInferenceProfilesCommand } = require("@aws-sdk/client-bedrock");
    const client = new BedrockClient({ region: env.AWS_REGION || env.AWS_DEFAULT_REGION || "us-east-1" });
    const models = [];
    let nextToken;
    do {
      const page = await client.send(
        new ListInferenceProfilesCommand({ typeEquals: "SYSTEM_DEFINED", maxResults: 1000, nextToken })
      );
      for (const p of page.inferenceProfileSummaries ?? []) {
        if (p.status === "ACTIVE") models.push({ id: p.inferenceProfileId, name: p.inferenceProfileName });
      }
      nextToken = page.nextToken;
    } while (nextToken);
    return models;
  },
};

// --- Deciding what changes (pure) ----------------------------------------------

const DATED = /\d{8}|\d{4}-\d{2}-\d{2}/;

// For one provider: which curated models are gone, and what replaces them.
// `live` is [{ id, name? }]. Returns { changes, unresolved, newer, skipped }.
export function planProvider(provider, entry, live, helpers) {
  const { rankReplacements, modelFamily, compareModelRecency } = helpers;
  const liveIds = live.map((m) => m.id);
  const liveSet = new Set(liveIds);
  const curated = entry.models.map((m) => m.id);
  const missing = curated.filter((id) => !liveSet.has(id));
  const result = { changes: [], unresolved: [], newer: [], skipped: null };

  // If most of the list vanished at once, the listing API changed or the key
  // sees a restricted view; don't rewrite the registry on that basis.
  if (liveIds.length === 0 || missing.length > curated.length / 2) {
    if (missing.length > 0) {
      result.skipped = `${missing.length} of ${curated.length} curated models are not listed; not changing anything`;
    }
    return result;
  }

  // Prefer aliases (claude-sonnet-5-5, gpt-5.2) over dated snapshots of them.
  const undated = liveIds.filter((id) => !DATED.test(id));
  const defaultModel = liveSet.has(entry.defaultModel) ? entry.defaultModel : "";
  const best = (id, available) => rankReplacements(id, available, defaultModel).find((r) => liveSet.has(r));
  for (const id of missing) {
    const replacement = best(id, undated) || best(id, liveIds);
    if (!replacement) {
      result.unresolved.push(id);
      continue;
    }
    const name = live.find((m) => m.id === replacement)?.name || replacement;
    result.changes.push({ provider, from: id, to: replacement, label: name });
  }

  // Newer models in a family we curate, for the report only.
  const families = new Map();
  for (const id of curated.filter((id) => liveSet.has(id))) {
    const family = modelFamily(id);
    const newest = families.get(family);
    if (!newest || compareModelRecency(id, newest) > 0) families.set(family, id);
  }
  for (const id of undated) {
    const newest = families.get(modelFamily(id));
    if (newest && !curated.includes(id) && compareModelRecency(id, newest) > 0) {
      result.newer.push(id);
    }
  }
  return result;
}

// --- Rewriting models.ts (pure) --------------------------------------------------

// [start, end) of `export const <name> ... = {` through its closing `};`.
function section(source, name) {
  const start = source.indexOf(`export const ${name}`);
  const end = start < 0 ? -1 : source.indexOf("\n};\n", start);
  if (end < 0) throw new Error(`can't find ${name} in models.ts`);
  return [start, end];
}

// [start, end) of a provider's `  name: {` ... `  },` entry within a section.
// Returns null for an empty entry written as `  name: {},`.
function providerBlock(source, [sectionStart, sectionEnd], provider) {
  const body = source.slice(sectionStart, sectionEnd);
  if (body.includes(`\n  ${provider}: {},`)) return null;
  const start = body.indexOf(`\n  ${provider}: {\n`);
  const end = start < 0 ? -1 : body.indexOf("\n  },", start);
  if (end < 0) throw new Error(`can't find the ${provider} entry in models.ts`);
  return [sectionStart + start, sectionStart + end];
}

const quote = (s) => JSON.stringify(s);

// Applies changes ({ provider, from, to, label }) to the text of models.ts.
export function applyChanges(source, changes, date) {
  for (const { provider, from, to, label } of changes) {
    // The curated list.
    const [start, end] = providerBlock(source, section(source, "MODEL_REGISTRY"), provider);
    let block = source.slice(start, end);
    const entryLine = new RegExp(`\\n[ \\t]*\\{ id: ${escapeRegExp(quote(from))}, label: [^\\n]*\\},`);
    if (!entryLine.test(block)) throw new Error(`can't find the ${from} entry in models.ts`);
    if (block.includes(`{ id: ${quote(to)},`)) {
      block = block.replace(entryLine, "");
    } else {
      block = block.replace(entryLine, (line) => {
        const indent = line.match(/^\n[ \t]*/)[0];
        return `${indent}{ id: ${quote(to)}, label: ${quote(label)} },`;
      });
    }
    block = block.replace(`defaultModel: ${quote(from)},`, `defaultModel: ${quote(to)},`);
    source = source.slice(0, start) + block + source.slice(end);

    // The provider's retirements: point existing ones at the new target, then
    // add this one.
    const retiredSection = section(source, "RETIRED_MODELS");
    const retired = providerBlock(source, retiredSection, provider);
    const entry = `    ${quote(from)}: ${quote(to)},`;
    const comment = `    // No longer listed by the provider (found by the model check, ${date}).`;
    if (retired === null) {
      const empty = source.indexOf(`\n  ${provider}: {},`, retiredSection[0]);
      const replacement = `\n  ${provider}: {\n${comment}\n${entry}\n  },`;
      source = source.slice(0, empty) + replacement + source.slice(empty + `\n  ${provider}: {},`.length);
      continue;
    }
    let body = source.slice(retired[0], retired[1]).split(`: ${quote(from)},`).join(`: ${quote(to)},`);
    if (!body.includes(`\n    ${quote(from)}:`)) {
      if (!body.includes(comment)) body += `\n${comment}`;
      body += `\n${entry}`;
    }
    source = source.slice(0, retired[0]) + body + source.slice(retired[1]);
  }
  return source;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// --- Main ------------------------------------------------------------------------

function renderReport(lines) {
  return lines.join("\n") + "\n";
}

async function main(argv, env) {
  const dryRun = argv.includes("--dry-run");
  const reportIndex = argv.indexOf("--report");
  const reportPath = reportIndex >= 0 ? argv[reportIndex + 1] : null;

  const helpers = await import(pathToFileURL(MODELS_TS).href);
  const { MODEL_REGISTRY } = helpers;
  const date = new Date().toISOString().slice(0, 10);

  const changes = [];
  const report = [];
  let checked = 0;
  for (const [provider, lister] of Object.entries(LISTERS)) {
    const entry = MODEL_REGISTRY[provider];
    let live;
    try {
      live = await lister(env);
    } catch (err) {
      report.push(`- **${provider}**: couldn't list models (${err.message.split("\n")[0]})`);
      continue;
    }
    if (live === null) {
      report.push(`- **${provider}**: not checked (no credentials)`);
      continue;
    }
    checked++;
    const plan = planProvider(provider, entry, live, helpers);
    changes.push(...plan.changes);
    const notes = [];
    for (const c of plan.changes) notes.push(`\`${c.from}\` is gone; replaced by \`${c.to}\``);
    for (const id of plan.unresolved) notes.push(`\`${id}\` is gone and has no replacement; **needs a human**`);
    if (plan.skipped) notes.push(plan.skipped);
    if (plan.newer.length) notes.push(`newer models listed: ${plan.newer.map((id) => `\`${id}\``).join(", ")}`);
    report.push(`- **${provider}**: ${notes.length ? notes.join("; ") : "all curated models are listed"}`);
  }
  report.push("- **azure**: not checked (deployment names are per-resource)");

  const header = changes.length
    ? [
        "These curated models in `scalene/scalene-gui/models.ts` are no longer listed by their providers.",
        "This PR replaces them with their newest same-family successors and adds the old IDs to",
        "`RETIRED_MODELS`, so saved selections are migrated. Please check the new labels.",
        "",
      ]
    : ["All checked curated models are still listed.", ""];
  const text = renderReport([...header, ...report]);
  process.stdout.write(text);
  if (reportPath) writeFileSync(reportPath, text);

  if (changes.length && !dryRun) {
    writeFileSync(MODELS_TS, applyChanges(readFileSync(MODELS_TS, "utf8"), changes, date));
  }
  if (checked === 0) {
    console.error("No provider could be checked (no credentials, or listing failed).");
  }
}

// Run only as a script (not when imported, including from `node -e`).
const evaluated = process.execArgv.some((a) => a === "-e" || a === "--eval" || a.startsWith("--eval="));
if (!evaluated && process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2), process.env).catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
