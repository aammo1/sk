import { readFile } from "node:fs/promises";
import readline from "node:readline/promises";
import { inspect, manage } from "./manager.mjs";

export const managementHelp = `
Catalog management — JSON contract version 1
  node scripts/add-product.mjs capabilities --json
  node scripts/add-product.mjs list --json
  node scripts/add-product.mjs show <id-or-slug> --json
  node scripts/add-product.mjs add --from product.json [--dry-run] [--yes] [--json]
  node scripts/add-product.mjs edit <id-or-slug> --from edit.json [--dry-run] [--yes] [--json]
  node scripts/add-product.mjs delete <id-or-slug> [--from decision.json] [--dry-run] [--yes] [--json]
  --expected-revision <sha256> may guard any mutation. Deltas require a revision.
  --from without a command remains creation. No arguments starts the French interview.
  Edit/delete request: {"version":1,...}; omitted fields preserve existing values.
  capabilities --json describes the complete contract; scripts/catalog/README.md has examples.
  Dry-run never prompts or writes, including when an upsell decision is needed.
`;

function args(argv) {
  const result = { command: null, target: undefined, yes: false, dryRun: false, json: false };
  const positionals = [];
  const seen = new Set();
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith("-")) {
      if (seen.has(arg)) throw new Error(`Repeated flag: ${arg}`);
      seen.add(arg);
      if (["--from", "--expected-revision"].includes(arg)) {
        const value = argv[++i];
        if (!value || value.startsWith("--")) throw new Error(`${arg} requires a value`);
        result[arg === "--from" ? "from" : "expectedRevision"] = value;
      } else if (arg === "--yes") result.yes = true;
      else if (arg === "--dry-run") result.dryRun = true;
      else if (arg === "--json") result.json = true;
      else if (["-h", "--help"].includes(arg)) result.help = true;
      else throw new Error(`Unknown flag: ${arg}`);
    } else positionals.push(arg);
  }
  result.command = positionals[0] ?? (result.from ? "add" : null);
  result.target = positionals[1];
  if (result.help) return result;
  if (!["capabilities", "list", "show", "add", "edit", "delete"].includes(result.command)) throw new Error("Specify capabilities/list/show/add/edit/delete; use --help");
  const targeted = ["show", "edit", "delete"].includes(result.command);
  if (targeted && !result.target) throw new Error(`${result.command} requires an id or slug`);
  if (positionals.length > (targeted ? 2 : 1)) throw new Error("Unexpected positional argument");
  if (["edit", "add"].includes(result.command) && !result.from) throw new Error(`${result.command} requires --from`);
  if (["capabilities", "list", "show"].includes(result.command) && (result.from || result.yes || result.dryRun || result.expectedRevision)) throw new Error("Mutation flags are not valid for inspection commands");
  return result;
}

// Options injection is intentionally only available to imported fixture tests.
export async function runManagementCli(root, argv, internal = {}) {
  const options = args(argv);
  if (options.help) { console.log(managementHelp); return; }
  let result;
  if (["capabilities", "list", "show"].includes(options.command)) result = await inspect(root, options.command, options.target);
  else {
    const request = options.from ? JSON.parse(await readFile(options.from, "utf8")) : { version: 1 };
    const execution = { ...internal, dryRun: options.dryRun, expectedRevision: options.expectedRevision };
    if (!options.dryRun && !options.yes) {
      // Validate and discover decisions before asking; revalidate under the write lock.
      const preview = await manage(root, options.command, options.target, request, { ...execution, dryRun: true });
      if (preview.decisionRequired) throw new Error("Explicit upsell disable/replaceWith decision required in --from JSON before deletion");
      if (!process.stdin.isTTY) throw new Error("Non-interactive mutation requires --yes (use --dry-run first)");
      const prompt = readline.createInterface({ input: process.stdin, output: process.stderr });
      try {
        const answer = await prompt.question(`${options.command} ${preview.target}: ${preview.writes.length} file(s). Confirm? [y/N] `);
        if (!["y", "yes", "o", "oui"].includes(answer.trim().toLowerCase())) result = { schemaVersion: 1, cancelled: true };
      } finally { prompt.close(); }
      execution.expectedRevision = preview.revision;
    }
    result ??= await manage(root, options.command, options.target, request, execution);
  }
  console.log(JSON.stringify(result, null, 2));
  return result;
}
