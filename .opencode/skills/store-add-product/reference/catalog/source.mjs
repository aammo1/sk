import ts from "typescript";
import { createHash } from "node:crypto";

export const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
export const encode = (value) => JSON.stringify(value, null, 2).replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
export const legacyLabels = ["0-3 mois", "3-6 mois", "6-9 mois"];

export function parse(source, filename = "catalog.ts") {
  const file = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  if (file.parseDiagnostics.length) throw new Error(`Invalid TypeScript in ${filename}`);
  return file;
}

export function declaration(file, name) {
  const matches = file.statements.flatMap((s) => ts.isVariableStatement(s) ? [...s.declarationList.declarations] : [])
    .filter((d) => ts.isIdentifier(d.name) && d.name.text === name);
  if (matches.length !== 1 || !matches[0].initializer) throw new Error(`Expected one ${name} declaration`);
  return matches[0].initializer;
}

function unwrap(node) {
  while (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node)) node = node.expression;
  return node;
}

export function properties(node) {
  node = unwrap(node);
  if (!ts.isObjectLiteralExpression(node)) throw new Error("Expected an object literal");
  const result = new Map();
  for (const p of node.properties) {
    if (!ts.isPropertyAssignment(p) || !(ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))) throw new Error("Unsupported object property");
    const key = p.name.text;
    if (result.has(key) || ["__proto__", "constructor", "prototype"].includes(key)) throw new Error(`Duplicate/unsafe property: ${key}`);
    result.set(key, p.initializer);
  }
  return result;
}

// These helpers are interpreted, never executed. Reject changed implementations rather
// than silently assigning the old meaning to a newly edited helper.
const helperSources = {
  variants: `export function variants(stock0: number, stock3: number, stock6: number): SizeVariant[] {
    const stock: Record<SizeLabel, number> = { "0-3 mois": stock0, "3-6 mois": stock3, "6-9 mois": stock6, };
    return (Object.keys(stock) as SizeLabel[]).map((label) => ({ label, stock: stock[label] }));
  }`,
  images: `function images(slug: string, count = DEFAULT_PHOTO_COUNT): string[] {
    return Array.from({ length: count }, (_, index) => \`/images/products/\${slug}-\${index + 1}.webp\`);
  }`,
  defaultColorway: `export function defaultColorway(slug: string, stock: SizeVariant[], imageCount = DEFAULT_PHOTO_COUNT,): ColorVariant {
    return { id: "ecru", label: "Écru", hex: "#F5F0E6", images: images(slug, imageCount), sizeVariants: stock, };
  }`,
};
function tokens(source) {
  function structure(node) {
    const children = [];
    ts.forEachChild(node, (child) => { children.push(structure(child)); });
    return [node.kind, ts.isSourceFile(node) ? null : (node.text ?? null), children];
  }
  return JSON.stringify(structure(parse(source)));
}

export function decoder(file) {
  const verified = new Set();
  function verify(name) {
    if (verified.has(name)) return;
    const helpers = file.statements.filter((s) => ts.isFunctionDeclaration(s) && s.name?.text === name);
    if (helpers.length !== 1 || tokens(helpers[0].getText(file)) !== tokens(helperSources[name])) {
      throw new Error(`Unsupported helper implementation: ${name}`);
    }
    verified.add(name);
    if (name !== "variants") {
      if (decode(declaration(file, "DEFAULT_PHOTO_COUNT")) !== 4) throw new Error("Unsupported DEFAULT_PHOTO_COUNT");
    }
    if (name === "defaultColorway") verify("images");
  }
  function decode(input) {
    const node = unwrap(input);
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isNumericLiteral(node)) return Number(node.text);
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (node.kind === ts.SyntaxKind.NullKeyword) return null;
    if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(node.operand)) return -Number(node.operand.text);
    if (ts.isArrayLiteralExpression(node)) return [...node.elements].map(decode);
    if (ts.isObjectLiteralExpression(node)) return Object.fromEntries([...properties(node)].map(([key, value]) => [key, decode(value)]));
    if (ts.isIdentifier(node) && ["FABRIC", "CARE"].includes(node.text)) {
      const value = unwrap(declaration(file, node.text));
      if (!ts.isStringLiteral(value) && !ts.isNoSubstitutionTemplateLiteral(value)) throw new Error(`Unsupported constant: ${node.text}`);
      return value.text;
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && Object.hasOwn(helperSources, node.expression.text)) {
      const name = node.expression.text;
      verify(name);
      const args = [...node.arguments].map(decode);
      if (name === "variants" && args.length === 3 && args.every((v) => Number.isSafeInteger(v) && v >= 0)) return args.map((stock, i) => ({ label: legacyLabels[i], stock }));
      const gallery = (slug, count = 4) => {
        if (typeof slug !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || !Number.isInteger(count) || count < 1 || count > 8) throw new Error("Invalid images() arguments");
        return Array.from({ length: count }, (_, i) => `/images/products/${slug}-${i + 1}.webp`);
      };
      if (name === "images" && args.length >= 1 && args.length <= 2) return gallery(...args);
      if (name === "defaultColorway" && args.length >= 2 && args.length <= 3 && Array.isArray(args[1])) return { id: "ecru", label: "Écru", hex: "#F5F0E6", images: gallery(args[0], args[2]), sizeVariants: args[1] };
      throw new Error(`Invalid ${name}() arguments`);
    }
    throw new Error(`Unsupported catalog expression: ${node.getText(file).slice(0, 100)}`);
  }
  return decode;
}

export function readCatalog(source) {
  const file = parse(source);
  const array = unwrap(declaration(file, "PRODUCTS"));
  if (!ts.isArrayLiteralExpression(array)) throw new Error("PRODUCTS must be an array literal");
  const decode = decoder(file);
  return { file, array, products: [...array.elements].map(decode), nodes: [...array.elements], decode };
}

export function patchRanges(source, edits) {
  for (const { start, end, text } of edits.sort((a, b) => b.start - a.start)) source = source.slice(0, start) + text + source.slice(end);
  return source;
}

export function emitCatalog(source, before, products) {
  const edits = [];
  before.products.forEach((old, index) => {
    const next = products.find((p) => p.id === old.id);
    const node = before.nodes[index];
    if (!next) {
      // Delete the element and its comma, keeping surrounding comments/trivia.
      const scanner = ts.createScanner(ts.ScriptTarget.Latest, true, ts.LanguageVariant.Standard, source.slice(node.end));
      const hasComma = scanner.scan() === ts.SyntaxKind.CommaToken;
      edits.push({ start: node.getStart(before.file), end: node.end, text: "" });
      if (hasComma) edits.push({ start: node.end + scanner.getTokenPos(), end: node.end + scanner.getTextPos(), text: "" });
    } else if (JSON.stringify(old) !== JSON.stringify(next)) {
      edits.push({ start: node.getStart(before.file), end: node.end, text: encode(next) });
    }
  });
  const added = products.filter((p) => !before.products.some((old) => old.id === p.id));
  if (added.length) edits.push({ start: before.array.getStart(before.file) + 1, end: before.array.getStart(before.file) + 1, text: `\n${added.map(encode).join(",\n")},\n` });
  const output = patchRanges(source, edits);
  if (JSON.stringify(readCatalog(output).products) !== JSON.stringify(products)) throw new Error("Emitted catalog does not match intended state");
  return output;
}

export function readOffer(source) {
  const file = parse(source, "funnel-config.ts");
  const props = properties(declaration(file, "UPSELL_OFFER"));
  const decode = decoder(file);
  if (!props.has("active") || !props.has("productId")) throw new Error("UPSELL_OFFER requires active/productId");
  const active = decode(props.get("active"));
  const productId = decode(props.get("productId"));
  if (typeof active !== "boolean" || typeof productId !== "string") throw new Error("Unsupported UPSELL_OFFER target");
  return { file, props, active, productId };
}

export function emitOffer(source, changes) {
  const offer = readOffer(source);
  const output = patchRanges(source, Object.entries(changes).map(([key, value]) => ({ start: offer.props.get(key).getStart(offer.file), end: offer.props.get(key).end, text: encode(value) })));
  const checked = readOffer(output);
  for (const [key, value] of Object.entries(changes)) if (checked[key] !== value) throw new Error("Emitted offer mismatch");
  return output;
}

export function collectionLabels(source) {
  const file = parse(source, "types.ts");
  const node = file.statements.find((s) => ts.isTypeAliasDeclaration(s) && s.name.text === "CollectionSlug");
  const types = node && ts.isUnionTypeNode(node.type) ? node.type.types : [node?.type];
  if (types.some((t) => !t || !ts.isLiteralTypeNode(t) || !ts.isStringLiteral(t.literal))) throw new Error("Unsupported CollectionSlug type");
  return types.map((t) => t.literal.text);
}
