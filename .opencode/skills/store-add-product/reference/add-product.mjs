import { existsSync, readFileSync, statSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import readline from "node:readline/promises";
import { pathToFileURL } from "node:url";
import sharp from "sharp";
import { manage, validateSizes } from "./catalog/manager.mjs";
import { readCatalog } from "./catalog/source.mjs";
import { runManagementCli, managementHelp } from "./catalog/cli.mjs";

const ROOT = path.resolve(import.meta.dirname, "..");
const PRODUCTS_PATH = path.join(ROOT, "lib", "data", "products.ts");
const TYPES_PATH = path.join(ROOT, "lib", "types.ts");
const IMAGES_DIR = path.join(ROOT, "public", "images", "products");
const IMAGE_WIDTH = 1000;
const IMAGE_HEIGHT = 1250;
const WEBP_QUALITY = 82;
const PHOTO_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"];
const MIN_PHOTO_COUNT = 1;
const MAX_PHOTO_COUNT = 8;
const DEFAULT_PHOTO_COUNT = 4;
const SLUG_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const HEX_REGEX = /^#[0-9A-Fa-f]{6}$/;
const FALLBACK_COLLECTIONS = ["fille", "garcon", "naissance", "accessoires"];
const COLLECTION_LABELS = {
  fille: "Fille",
  garcon: "Garçon",
  naissance: "Naissance",
  accessoires: "Accessoires",
};
const PRODUCT_TAG_ORDER = ["promotion", "best-seller", "new", "gift"];
const PRODUCT_TAG_LABELS = {
  promotion: "Promotion",
  "best-seller": "Best-seller",
  new: "Nouveauté",
  gift: "Cadeau",
};
const JSON_KEYS = new Set([
  "name",
  "slug",
  "tagline",
  "price",
  "compareAtPrice",
  "collections",
  "collection", // legacy, normalisé vers « collections »
  "colorways",
  "description",
  "fabric",
  "care",
  "crossSellIds",
  "tags",
]);
const COLORWAY_KEYS = new Set(["label", "photosDir", "hex", "stock", "sizeVariants"]);
const CATALOG_FABRIC = "100% coton peigné, certifié OEKO-TEX®";
const CATALOG_CARE = "Lavage machine 30° — sèche-linge déconseillé";
const USAGE = `Assistant d'ajout de produit HelloBaby

Utilisation :
  node scripts/add-product.mjs
      Mode interactif (questionnaire en français).

  node scripts/add-product.mjs --from <fichier.json> [--yes]
      Mode non interactif : valide un JSON produit puis exécute le même pipeline
      (conversion WebP, insertion du bloc, tsc, lint).

Options :
  --from <fichier.json>  Chemin du JSON décrivant le produit.
  --yes                  Saute la confirmation du récapitulatif (mode --from uniquement).
  -h, --help             Affiche cette aide.

Champs JSON : name, slug, tagline, price, compareAtPrice, collections, colorways
(label, photosDir, hex, stock), description, fabric, care, crossSellIds, tags.
Chaque photosDir doit contenir 1 à 8 fichiers jpg/jpeg/png/webp, triés par nom.
Tags : tableau vide accepté ; IDs : promotion, best-seller, new, gift ; sortie dans cet ordre.
« promotion » requiert compareAtPrice > price et une remise arrondie à l'entier inférieur d'au moins 1 %.`;

function unescape(value) {
  return value.replace(/\\(["\\])/g, "$1");
}

function tsString(value) {
  return JSON.stringify(value).replaceAll("\u2028", "\\u2028").replaceAll("\u2029", "\\u2029");
}

export function slugify(text) {
  return text
    .replace(/[œŒ]/g, "oe")
    .replace(/[æÆ]/g, "ae")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[\s-]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

function toHex(r, g, b) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return `#${[r, g, b]
    .map((v) => clamp(v).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;
}

function swatch(rgb) {
  return `\x1b[48;2;${rgb[0]};${rgb[1]};${rgb[2]}m  \x1b[0m`;
}

function parseCollections(source) {
  const match = source.match(/export type CollectionSlug = ([^;]+);/);
  if (!match) return FALLBACK_COLLECTIONS;
  const values = [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  return values.length ? values : FALLBACK_COLLECTIONS;
}

function parseConstant(source, name) {
  const match = source.match(new RegExp(`const ${name} = "((?:[^"\\\\]|\\\\.)*)";`));
  return match ? unescape(match[1]) : null;
}

function collectionLabel(slug) {
  return COLLECTION_LABELS[slug] ?? slug;
}

export function normalizeProductTags(rawTags) {
  const errors = [];
  if (rawTags === undefined) return { errors, tags: [] };
  if (!Array.isArray(rawTags) || rawTags.some((tag) => typeof tag !== "string")) {
    errors.push(`tags : tableau de chaînes attendu (valeurs possibles : ${PRODUCT_TAG_ORDER.join(", ")}).`);
    return { errors, tags: [] };
  }

  const unknownTags = [...new Set(rawTags.filter((tag) => !PRODUCT_TAG_ORDER.includes(tag)))];
  const duplicateTags = [
    ...new Set(rawTags.filter((tag, index) => rawTags.indexOf(tag) !== index)),
  ];
  if (unknownTags.length) {
    errors.push(`tags : identifiant(s) inconnu(s) — ${unknownTags.map((tag) => `« ${tag} »`).join(", ")}.`);
  }
  if (duplicateTags.length) {
    errors.push(`tags : doublon(s) interdit(s) — ${duplicateTags.map((tag) => `« ${tag} »`).join(", ")}.`);
  }

  return {
    errors,
    tags: errors.length ? [] : PRODUCT_TAG_ORDER.filter((tag) => rawTags.includes(tag)),
  };
}

export function promotionDiscountPercent(price, compareAtPrice) {
  if (
    !Number.isInteger(price) ||
    !Number.isInteger(compareAtPrice) ||
    price <= 0 ||
    compareAtPrice <= price
  ) {
    return null;
  }
  const discountPercent = Math.floor(((compareAtPrice - price) * 100) / compareAtPrice);
  return discountPercent >= 1 ? discountPercent : null;
}

function hexToRgb(hex) {
  return [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
}

function imagePrefix(color, index, slug) {
  return index === 0 ? slug : `${slug}-${color.id}`;
}

function validateSlug(slug, existing, imageEntries) {
  if (!SLUG_REGEX.test(slug)) {
    return "Format invalide : minuscules, chiffres et tirets uniquement (ex. pyjama-petites-etoiles).";
  }
  if (existing.some((p) => p.id === slug || p.slug === slug)) {
    return `« ${slug} » est déjà utilisé comme id ou slug d'un produit existant.`;
  }
  const collision = imageEntries.find((entry) => entry.startsWith(slug));
  if (collision) {
    return `Une image existante entre en collision : public/images/products/${collision}`;
  }
  return null;
}

async function detectColor(photoPath) {
  const stats = await sharp(photoPath).stats();
  if (stats.dominant) {
    const { r, g, b } = stats.dominant;
    return { hex: toHex(r, g, b), rgb: [r, g, b] };
  }
  const rgb = stats.channels.slice(0, 3).map((c) => Math.round(c.mean));
  return { hex: toHex(rgb[0], rgb[1], rgb[2]), rgb };
}

export async function listPhotos(rawDir) {
  const dirPath = path.isAbsolute(rawDir) ? rawDir : path.resolve(process.cwd(), rawDir);
  if (!existsSync(dirPath) || !statSync(dirPath).isDirectory()) {
    return { error: `Dossier introuvable : ${rawDir}` };
  }
  const found = (await readdir(dirPath))
    .filter((entry) => PHOTO_EXTENSIONS.includes(path.extname(entry).toLowerCase()))
    .sort();
  if (found.length < MIN_PHOTO_COUNT || found.length > MAX_PHOTO_COUNT) {
    return {
      error: `${MIN_PHOTO_COUNT} à ${MAX_PHOTO_COUNT} photos requises — ${found.length} trouvée(s) dans « ${rawDir} ».`,
    };
  }
  return { photos: found.map((entry) => path.join(dirPath, entry)) };
}

export async function processProductImage(source, destination) {
  await sharp(source)
    .autoOrient()
    .resize({
      width: IMAGE_WIDTH,
      height: IMAGE_HEIGHT,
      fit: "inside",
      withoutEnlargement: true,
    })
    .webp({ quality: WEBP_QUALITY })
    .toFile(destination);
}

export function buildProductBlock(product) {
  const lines = [
    "  {",
    `    id: ${tsString(product.slug)},`,
    `    slug: ${tsString(product.slug)},`,
    `    name: ${tsString(product.name)},`,
    `    tagline: ${tsString(product.tagline)},`,
    `    price: ${product.price},`,
  ];
  if (product.compareAtPrice !== null) {
    lines.push(`    compareAtPrice: ${product.compareAtPrice},`);
  }
  const mono =
    product.colorways.length === 1 &&
    !product.colorways[0].sizeVariants &&
    product.colorways[0].id === "ecru" &&
    product.colorways[0].label === "Écru";
  if (mono) {
    const [s0, s3, s6] = product.colorways[0].stock;
    const photoCount = product.colorways[0].photos?.length ?? DEFAULT_PHOTO_COUNT;
    const countArg = photoCount === DEFAULT_PHOTO_COUNT ? "" : `, ${photoCount}`;
    lines.push(
      `    colorVariants: [defaultColorway(${tsString(product.slug)}, variants(${s0}, ${s3}, ${s6})${countArg})],`
    );
  } else {
    lines.push("    colorVariants: [");
    product.colorways.forEach((color, index) => {
      const imageArg = imagePrefix(color, index, product.slug);
      const photoCount = color.photos?.length ?? DEFAULT_PHOTO_COUNT;
      const countArg = photoCount === DEFAULT_PHOTO_COUNT ? "" : `, ${photoCount}`;
      lines.push("      {");
      lines.push(`        id: ${tsString(color.id)},`);
      lines.push(`        label: ${tsString(color.label)},`);
      lines.push(`        hex: ${tsString(color.hex)},`);
      lines.push(`        images: images(${tsString(imageArg)}${countArg}),`);
      lines.push(
        color.sizeVariants
          ? `        sizeVariants: ${JSON.stringify(color.sizeVariants)},`
          : `        sizeVariants: variants(${color.stock[0]}, ${color.stock[1]}, ${color.stock[2]}),`
      );
      lines.push("      },");
    });
    lines.push("    ],");
  }
  lines.push(`    collections: [${product.collections.map(tsString).join(", ")}],`);
  lines.push(`    crossSellIds: [${product.crossSellIds.map(tsString).join(", ")}],`);
  const { tags } = normalizeProductTags(product.tags);
  lines.push(`    tags: [${tags.map(tsString).join(", ")}],`);
  lines.push("    description:");
  lines.push(`      ${tsString(product.description)},`);
  lines.push(product.fabricRef ? "    fabric: FABRIC," : `    fabric: ${tsString(product.fabricValue)},`);
  lines.push(product.careRef ? "    care: CARE," : `    care: ${tsString(product.careValue)},`);
  lines.push("  },");
  return lines.join("\n");
}

async function readDescription(raw) {
  const trimmed = raw.trim();
  const asPath = path.isAbsolute(trimmed) ? trimmed : path.resolve(process.cwd(), trimmed);
  if (existsSync(asPath) && statSync(asPath).isFile()) {
    const content = await readFile(asPath, "utf8");
    return content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .join(" ")
      .trim();
  }
  return trimmed.replace(/\s*\n\s*/g, " ").trim();
}

async function askHex(rl, photoPath) {
  const { hex, rgb } = await detectColor(photoPath);
  console.log(`  → couleur détectée : ${hex} ${swatch(rgb)}`);
  for (;;) {
    const answer = (await rl.question(`  Couleur (Entrée = accepter ${hex}, ou saisissez #RRGGBB) : `)).trim();
    if (!answer) return { hex, rgb };
    if (HEX_REGEX.test(answer)) return { hex: answer.toUpperCase(), rgb: null };
    console.log("  ✗ Hex invalide — format attendu : #RRGGBB.");
  }
}

async function askRequired(rl, prompt, error) {
  for (;;) {
    const value = (await rl.question(prompt)).trim();
    if (value) return value;
    console.log(`  ✗ ${error}`);
  }
}

async function askInt(rl, prompt, min = 0) {
  for (;;) {
    const value = (await rl.question(prompt)).trim();
    const n = Number(value);
    if (Number.isInteger(n) && n >= min) return n;
    console.log(`  ✗ Nombre entier ≥ ${min} attendu.`);
  }
}

async function askYes(rl, prompt) {
  const value = (await rl.question(prompt)).trim().toLowerCase();
  return ["y", "yes", "o", "oui"].includes(value);
}

function createPrompt() {
  if (process.stdin.isTTY) {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.on("SIGINT", () => {
      console.log("\nInterrompu — aucune modification effectuée.");
      process.exit(1);
    });
    return { question: (prompt) => rl.question(prompt), close: () => rl.close() };
  }
  const lines = readFileSync(0, "utf8").split(/\r?\n/);
  while (lines.length && lines[lines.length - 1] === "") lines.pop();
  let index = 0;
  return {
    question: async (prompt) => {
      process.stdout.write(prompt);
      if (index >= lines.length) {
        throw new Error("Réponses manquantes : l'entrée standard s'est terminée avant la fin du questionnaire.");
      }
      const line = lines[index];
      index += 1;
      process.stdout.write(`${line}\n`);
      return line;
    },
    close: () => {},
  };
}

function printHelp() {
  console.log(USAGE);
  console.log(managementHelp);
}

function parseArgs(argv) {
  const options = { from: null, yes: false, help: false };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === "--from") {
      const value = argv[index + 1];
      if (value === undefined) {
        console.error("✗ --from requiert un chemin de fichier JSON.");
        process.exit(1);
      }
      options.from = value;
      index += 1;
    } else if (arg === "--yes") {
      options.yes = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      console.error(`✗ Argument inconnu : ${arg}`);
      printHelp();
      process.exit(1);
    }
  }
  return options;
}

async function loadContext() {
  if (!existsSync(PRODUCTS_PATH)) {
    console.error("✗ lib/data/products.ts introuvable — abandon.");
    process.exit(1);
  }
  if (!existsSync(IMAGES_DIR)) {
    console.error("✗ public/images/products/ introuvable — abandon.");
    process.exit(1);
  }
  const source = await readFile(PRODUCTS_PATH, "utf8");
  const existing = readCatalog(source).products;
  const typesSource = await readFile(TYPES_PATH, "utf8");
  const collectionSlugs = parseCollections(typesSource);
  const fabricDefault = parseConstant(source, "FABRIC") ?? CATALOG_FABRIC;
  const careDefault = parseConstant(source, "CARE") ?? CATALOG_CARE;
  const imageEntries = await readdir(IMAGES_DIR);
  return { source, existing, collectionSlugs, fabricDefault, careDefault, imageEntries };
}

function printRecap(product) {
  console.log(`  Nom         : ${product.name}`);
  console.log(`  Slug        : ${product.slug}`);
  console.log(
    `  Prix        : ${product.price} MAD${product.compareAtPrice !== null ? ` (prix barré : ${product.compareAtPrice} MAD)` : ""}`
  );
  console.log(`  Collection  : ${product.collections.map(collectionLabel).join(", ")}`);
  const mono =
    product.colorways.length === 1 &&
    product.colorways[0].id === "ecru" &&
    product.colorways[0].label === "Écru";
  product.colorways.forEach((color, index) => {
    const effectiveHex = mono ? "#F5F0E6" : color.hex;
    const rgb = color.rgb ?? hexToRgb(effectiveHex);
    const photoCount = color.photos.length;
    console.log(`  Coloris ${index + 1} : ${color.label} — ${effectiveHex} ${swatch(rgb)}`);
    console.log(`    images : ${photoCount} photo${photoCount === 1 ? "" : "s"}, noms WebP versionnés par contenu`);
    console.log(
      color.sizeVariants
        ? `    stock  : ${color.sizeVariants.map((size) => `${size.label} ×${size.stock}`).join(" · ")}`
        : `    stock  : 0-3 mois ×${color.stock[0]} · 3-6 mois ×${color.stock[1]} · 6-9 mois ×${color.stock[2]}`
    );
  });
  if (mono) console.log("  (coloris unique « Écru » → raccourci defaultColorway, hex #F5F0E6 du catalogue)");
  console.log(`  Tissus      : ${product.fabricRef ? "FABRIC (défaut)" : `« ${product.fabricValue} » (personnalisé)`}`);
  console.log(`  Entretien   : ${product.careRef ? "CARE (défaut)" : `« ${product.careValue} » (personnalisé)`}`);
  console.log(`  Description : ${product.description.slice(0, 90)}${product.description.length > 90 ? "…" : ""}`);
  console.log(`  Cross-sells : ${product.crossSellIds.length ? product.crossSellIds.join(", ") : "aucun"}`);
  console.log(`  Tags        : ${product.tags.length ? product.tags.map((tag) => PRODUCT_TAG_LABELS[tag]).join(", ") : "Aucun"}`);
}

async function runPipeline(context, product) {
  const result = await manage(ROOT, "add", undefined, {}, { preparedProduct: product, expectedSource: context.source });
  console.log(`\n✓ Produit ajouté et vérifié : /produits/${product.slug}`);
  console.log("Images WebP versionnées par contenu :", result.imageWrites.join(", "));
}

function parseJsonText(value, field, fallback, push) {
  if (value === undefined || value === null) return { ref: true, value: fallback };
  if (typeof value !== "string" || !value.trim()) {
    push(`${field} : null (valeur par défaut du catalogue) ou chaîne non vide attendu.`);
    return null;
  }
  return { ref: false, value: value.trim() };
}

export async function validateJsonProduct(raw, context) {
  const errors = [];
  const push = (message) => errors.push(message);
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { errors: ["La racine du JSON doit être un objet produit."], product: null };
  }
  for (const key of Object.keys(raw)) {
    if (!JSON_KEYS.has(key)) {
      push(`Clé inconnue « ${key} » — clés attendues : ${[...JSON_KEYS].join(", ")}.`);
    }
  }

  let name = null;
  if (typeof raw.name === "string" && raw.name.trim()) name = raw.name.trim();
  else push("name : requis, chaîne non vide.");

  let slug = null;
  if (raw.slug === undefined || raw.slug === null) {
    if (name) slug = slugify(name);
  } else if (typeof raw.slug === "string" && raw.slug.trim()) {
    slug = raw.slug.trim();
  } else {
    push("slug : chaîne non vide attendue, ou clé omise pour dériver du nom.");
  }
  if (slug) {
    const error = validateSlug(slug, context.existing, context.imageEntries);
    if (error) push(`slug : ${error}`);
  }

  let tagline = null;
  if (typeof raw.tagline === "string" && raw.tagline.trim()) tagline = raw.tagline.trim();
  else push("tagline : requise, chaîne non vide.");

  let price = null;
  if (Number.isInteger(raw.price) && raw.price > 0) price = raw.price;
  else push("price : nombre entier > 0 requis (prix en MAD).");

  let compareAtPrice = null;
  if (raw.compareAtPrice !== undefined && raw.compareAtPrice !== null) {
    if (!Number.isInteger(raw.compareAtPrice)) {
      push("compareAtPrice : nombre entier attendu, ou null pour aucun prix barré.");
    } else if (price !== null && raw.compareAtPrice <= price) {
      push(`compareAtPrice : doit être un entier supérieur au prix (${price} MAD).`);
    } else if (price !== null) {
      compareAtPrice = raw.compareAtPrice;
    }
  }

  const normalizedTags = normalizeProductTags(raw.tags);
  normalizedTags.errors.forEach(push);
  const tags = normalizedTags.tags;
  if (
    tags.includes("promotion") &&
    price !== null &&
    promotionDiscountPercent(price, compareAtPrice) === null
  ) {
    push(
      "tags : « promotion » requiert compareAtPrice entier supérieur au prix et une remise arrondie à l'entier inférieur d'au moins 1 %."
    );
  }

  let collections = null;
  const slugsList = context.collectionSlugs.join(" », « ");
  if (raw.collections !== undefined && raw.collections !== null) {
    if (
      !Array.isArray(raw.collections) ||
      raw.collections.length < 1 ||
      raw.collections.some((c) => typeof c !== "string" || !c.trim())
    ) {
      push(`collections : tableau non vide de chaînes attendu (valeurs possibles : « ${slugsList} »).`);
    } else {
      const slugs = [...new Set(raw.collections.map((c) => c.trim()))];
      const bad = slugs.filter((c) => !context.collectionSlugs.includes(c));
      if (bad.length) {
        push(
          `collections : valeur(s) inconnue(s) — ${bad.map((c) => `« ${c} »`).join(", ")} (valeurs possibles : « ${slugsList} »).`
        );
      } else {
        collections = slugs;
        if (raw.collection !== undefined && raw.collection !== null) {
          console.warn("⚠ « collection » ignoré : « collections » est fourni (« collection » est déprécié).");
        }
      }
    }
  } else if (raw.collection !== undefined && raw.collection !== null) {
    if (typeof raw.collection === "string" && context.collectionSlugs.includes(raw.collection)) {
      console.warn(
        "⚠ « collection » (chaîne unique) est déprécié — utilisez « collections » (tableau). Valeur normalisée en tableau à un élément."
      );
      collections = [raw.collection];
    } else {
      push(`collection : doit être l'une des valeurs « ${slugsList} » — ou utilisez « collections » (tableau).`);
    }
  } else {
    push(`collections : requis — tableau de valeurs parmi « ${slugsList} ».`);
  }

  let colorways = [];
  if (!Array.isArray(raw.colorways) || raw.colorways.length < 1) {
    push("colorways : tableau d'au moins un coloris requis.");
  } else {
    for (let index = 0; index < raw.colorways.length; index++) {
      const entry = raw.colorways[index];
      const where = `colorways[${index}]`;
      if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
        push(`${where} : objet attendu ({ label, photosDir, hex, stock }).`);
        continue;
      }
      for (const key of Object.keys(entry)) {
        if (!COLORWAY_KEYS.has(key)) {
          push(`${where} : clé inconnue « ${key} » — clés attendues : label, photosDir, hex, stock.`);
        }
      }
      let label = null;
      if (typeof entry.label === "string" && entry.label.trim()) label = entry.label.trim();
      else push(`${where}.label : requis, chaîne non vide.`);

      let photos = null;
      if (typeof entry.photosDir === "string" && entry.photosDir.trim()) {
        if (!path.isAbsolute(entry.photosDir)) {
          push(`${where}.photosDir : chemin absolu requis (reçu « ${entry.photosDir} »).`);
        } else {
          const found = await listPhotos(entry.photosDir);
          if (found.error) push(`${where}.photosDir : ${found.error}`);
          else photos = found.photos;
        }
      } else {
        push(`${where}.photosDir : chemin absolu d'un dossier contenant 1 à 8 photos (jpg/jpeg/png/webp).`);
      }

      let hex = null;
      let rgb = null;
      if (entry.hex === undefined || entry.hex === null) {
        if (photos) {
          try {
            const detected = await detectColor(photos[0]);
            hex = detected.hex;
            rgb = detected.rgb;
          } catch {
            push(`${where}.hex : détection automatique impossible sur ${photos[0]} — fournissez un hex #RRGGBB.`);
          }
        }
      } else if (typeof entry.hex === "string" && HEX_REGEX.test(entry.hex)) {
        hex = entry.hex.toUpperCase();
      } else {
        push(`${where}.hex : « #RRGGBB » attendu, ou null pour la détection automatique depuis la photo 1.`);
      }

      let stock = null;
      let sizeVariants;
      if (entry.sizeVariants !== undefined) {
        if (entry.stock !== undefined) push(`${where} : fournissez stock OU sizeVariants, pas les deux.`);
        try {
          validateSizes(entry.sizeVariants);
          sizeVariants = entry.sizeVariants;
        } catch (error) { push(`${where}.sizeVariants : ${error.message}`); }
      } else if (
        Array.isArray(entry.stock) &&
        entry.stock.length === 3 &&
        entry.stock.every((n) => Number.isSafeInteger(n) && n >= 0)
      ) {
        stock = entry.stock;
      } else {
        push(`${where}.stock : tableau de 3 entiers ≥ 0 requis (stock 0-3, 3-6 et 6-9 mois).`);
      }

      let id = null;
      if (label) {
        const candidate = slugify(label);
        if (!SLUG_REGEX.test(candidate)) {
          push(`${where}.label : impossible de dériver un identifiant de « ${label} ».`);
        } else if (colorways.some((c) => c.id === candidate)) {
          push(`${where}.label : identifiant « ${candidate} » déjà utilisé pour ce produit.`);
        } else {
          id = candidate;
        }
      }

      if (id && photos && hex !== null && (stock || sizeVariants)) {
        colorways.push({ id, label, hex, rgb, photos, stock, ...(sizeVariants ? { sizeVariants } : {}) });
      }
    }
  }

  let description = null;
  if (typeof raw.description === "string" && raw.description.trim()) {
    description = raw.description.replace(/\s*\n\s*/g, " ").trim();
  }
  if (!description) {
    push("description : requise, chaîne non vide (les retours à la ligne sont remplacés par des espaces).");
  }

  const fabric = parseJsonText(raw.fabric, "fabric", context.fabricDefault, push);
  const care = parseJsonText(raw.care, "care", context.careDefault, push);

  let crossSellIds = [];
  if (raw.crossSellIds !== undefined && raw.crossSellIds !== null) {
    if (!Array.isArray(raw.crossSellIds) || raw.crossSellIds.some((id) => typeof id !== "string" || !id.trim())) {
      push('crossSellIds : tableau d\'identifiants produits attendu (ex. ["produit-associe"]), ou clé omise.');
    } else {
      const ids = [...new Set(raw.crossSellIds.map((id) => id.trim()))];
      const bad = ids.filter((id) => !context.existing.some((p) => p.id === id || p.slug === id));
      if (bad.length) {
        push(
          `crossSellIds : produit(s) introuvable(s) dans lib/data/products.ts — ${bad
            .map((id) => `« ${id} »`)
            .join(", ")}.`
        );
      } else {
        crossSellIds = ids;
      }
    }
  }

  if (errors.length) return { errors, product: null };
  return {
    errors,
    product: {
      slug,
      name,
      tagline,
      price,
      compareAtPrice,
      collections,
      colorways,
      description,
      fabricRef: fabric.ref,
      fabricValue: fabric.value,
      careRef: care.ref,
      careValue: care.value,
      crossSellIds,
      tags,
    },
  };
}

async function runFromMode(context, options) {
  const filePath = path.isAbsolute(options.from) ? options.from : path.resolve(process.cwd(), options.from);
  if (!existsSync(filePath)) {
    console.error(`✗ Fichier JSON introuvable : ${filePath}`);
    process.exit(1);
  }
  let raw;
  try {
    raw = JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    console.error(`✗ JSON invalide (${filePath}) : ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }

  const { errors, product } = await validateJsonProduct(raw, context);
  if (errors.length || !product) {
    console.error(`\n✗ ${errors.length} problème(s) détecté(s) dans le fichier JSON :`);
    errors.forEach((message, index) => console.error(`  ${index + 1}. ${message}`));
    console.error("\nAucune modification effectuée — corrigez puis relancez.");
    process.exit(1);
  }

  console.log("\n── Récapitulatif ──");
  printRecap(product);

  if (!options.yes) {
    const rl = createPrompt();
    const confirmed = await askYes(rl, "\nTout est correct ? (y/N) : ");
    rl.close();
    if (!confirmed) {
      console.log("Annulé — rien n'a été écrit.");
      return;
    }
  }

  await runPipeline(context, product);
}

async function runInterview(context) {
  const rl = createPrompt();

  console.log("\nBienvenue dans l'assistant d'ajout de produit HelloBaby !");
  console.log("Entrée accepte la valeur par défaut (entre parenthèses). Ctrl+C pour quitter à tout moment.");

  console.log("\n── 1/11 · Nom du produit ──");
  let productName = "";
  let slug = "";
  for (;;) {
    productName = await askRequired(
      rl,
      "Nom affiché du produit (ex. Pyjama « Petites Étoiles ») : ",
      "Le nom est requis."
    );
    const derived = slugify(productName);
    console.log(`  → slug dérivé : ${derived}`);
    let valid = false;
    while (!valid) {
      const answer = (await rl.question(`  Slug (Entrée = « ${derived} ») : `)).trim() || derived;
      const error = validateSlug(answer, context.existing, context.imageEntries);
      if (error) {
        console.log(`  ✗ ${error}`);
        continue;
      }
      slug = answer;
      valid = true;
    }
    break;
  }

  console.log("\n── 2/11 · Accroche ──");
  const tagline = await askRequired(
    rl,
    "Accroche courte (ex. La douceur qui berce les premières nuits) : ",
    "L'accroche est requise."
  );

  console.log("\n── 3/11 · Prix ──");
  let price = -1;
  for (;;) {
    const value = (await rl.question("Prix en MAD, nombre entier (ex. 249) : ")).trim();
    const n = Number(value);
    if (Number.isInteger(n) && n >= 1) {
      price = n;
      break;
    }
    console.log("  ✗ Nombre entier ≥ 1 attendu.");
  }
  let compareAtPrice = null;
  for (;;) {
    const answer = (await rl.question("Prix barré en MAD (Entrée = aucun ; doit être supérieur au prix) : ")).trim();
    if (!answer) break;
    const n = Number(answer);
    if (Number.isInteger(n) && n > price) {
      compareAtPrice = n;
      break;
    }
    console.log(`  ✗ Nombre entier supérieur à ${price} attendu.`);
  }

  console.log("\n── 4/11 · Collections ──");
  context.collectionSlugs.forEach((collectionSlug, i) => {
    console.log(`  ${i + 1}. ${collectionLabel(collectionSlug)} (« ${collectionSlug} »)`);
  });
  let collections = [];
  for (;;) {
    const raw = (await rl.question(
      `Numéros séparés par des virgules (ex: 1,3 — une ou plusieurs parmi 1-${context.collectionSlugs.length}) : `
    )).trim();
    if (!raw) {
      console.log("  ✗ Sélection requise : au moins une collection.");
      continue;
    }
    const parts = raw.split(",").map((part) => part.trim()).filter(Boolean);
    const invalid = parts.find((part) => {
      const n = Number(part);
      return !Number.isInteger(n) || n < 1 || n > context.collectionSlugs.length;
    });
    if (invalid) {
      console.log(`  ✗ Numéro invalide : ${invalid} (1-${context.collectionSlugs.length}).`);
      continue;
    }
    collections = [...new Set(parts.map((part) => context.collectionSlugs[Number(part) - 1]))];
    break;
  }

  console.log("\n── 5/11 · Coloris ──");
  const count = await askInt(rl, "Nombre de coloris (1 = un seul coloris) : ", 1);

  const colorways = [];
  for (let index = 0; index < count; index++) {
    console.log(`\n── 6/11 · Coloris ${index + 1} sur ${count} ──`);
    let label = "";
    let colorId = "";
    for (;;) {
      label = await askRequired(rl, "Label de la couleur (ex. Écru, Rose poudré) : ", "Le label est requis.");
      const candidate = slugify(label);
      if (!SLUG_REGEX.test(candidate)) {
        console.log("  ✗ Impossible de dériver un identifiant de ce label.");
        continue;
      }
      if (colorways.some((c) => c.id === candidate)) {
        console.log(`  ✗ Identifiant « ${candidate} » déjà utilisé pour ce produit.`);
        continue;
      }
      colorId = candidate;
      break;
    }
    const prefix = imagePrefix({ id: colorId }, index, slug);
    let photos = null;
    for (;;) {
      const raw = await askRequired(
        rl,
        "Chemin du dossier contenant 1 à 8 photos (jpg/jpeg/png/webp, triées par nom → positions 1 à N) : ",
        "Le chemin est requis."
      );
      const found = await listPhotos(raw);
      if (found.error) {
        console.log(`  ✗ ${found.error}`);
        continue;
      }
      photos = found.photos;
      const photoCount = photos.length;
      const imageRange = photoCount === 1 ? `${prefix}-1.webp` : `${prefix}-1.webp … ${prefix}-${photoCount}.webp`;
      console.log(`  ✓ ${photoCount} photo${photoCount === 1 ? " trouvée" : "s trouvées"} :`);
      photos.forEach((photo, i) => console.log(`    ${i + 1}. ${path.basename(photo)}`));
      console.log(`  → images cibles : ${imageRange}`);
      break;
    }
    const color = await askHex(rl, photos[0]);
    const stock0 = await askInt(rl, "Stock « 0-3 mois » : ");
    const stock3 = await askInt(rl, "Stock « 3-6 mois » : ");
    const stock6 = await askInt(rl, "Stock « 6-9 mois » : ");
    colorways.push({ id: colorId, label, hex: color.hex, rgb: color.rgb, photos, stock: [stock0, stock3, stock6] });
  }

  console.log("\n── 7/11 · Description ──");
  let description = "";
  for (;;) {
    const raw = await askRequired(
      rl,
      "Collez la description en une ligne, OU donnez le chemin d'un fichier .txt : ",
      "La description est requise."
    );
    description = await readDescription(raw);
    if (description) break;
    console.log("  ✗ Description vide.");
  }

  console.log("\n── 8/11 · Tissus & entretien ──");
  console.log("  Entrée = valeurs par défaut du catalogue (références FABRIC / CARE).");
  const fabricAnswer = (await rl.question(`  Tissu (Entrée = « ${context.fabricDefault} ») : `)).trim();
  const careAnswer = (await rl.question(`  Entretien (Entrée = « ${context.careDefault} ») : `)).trim();

  console.log("\n── 9/11 · Produits suggérés (cross-sells) ──");
  if (!context.existing.length) {
    console.log("  Aucun produit existant.");
  }
  context.existing.forEach((p, i) => console.log(`  ${i + 1}. ${p.name} — ${p.id}`));
  let crossSellIds = [];
  for (;;) {
    const raw = (await rl.question("Numéros séparés par des virgules (Entrée = aucun) : ")).trim();
    if (!raw) break;
    const parts = raw.split(",").map((part) => part.trim()).filter(Boolean);
    const invalid = parts.find((part) => {
      const n = Number(part);
      return !Number.isInteger(n) || n < 1 || n > context.existing.length;
    });
    if (invalid) {
      console.log(`  ✗ Numéro invalide : ${invalid} (1-${context.existing.length}).`);
      continue;
    }
    crossSellIds = [...new Set(parts.map((part) => context.existing[Number(part) - 1].id))];
    break;
  }

  console.log("\n── 10/11 · Tags ──");
  PRODUCT_TAG_ORDER.forEach((tag, index) => {
    console.log(`  ${index + 1}. ${PRODUCT_TAG_LABELS[tag]} (« ${tag} »)`);
  });
  let tags = [];
  for (;;) {
    const raw = (await rl.question("Numéros séparés par des virgules (Entrée = aucun) : ")).trim();
    if (!raw) break;
    const parts = raw.split(",").map((part) => part.trim());
    const numbers = parts.map(Number);
    const invalid = parts.find((part, index) => {
      const number = numbers[index];
      return !part || !Number.isInteger(number) || number < 1 || number > PRODUCT_TAG_ORDER.length;
    });
    if (invalid !== undefined) {
      console.log(`  ✗ Numéro invalide : ${invalid || "vide"} (1-${PRODUCT_TAG_ORDER.length}).`);
      continue;
    }
    const duplicate = numbers.find((number, index) => numbers.indexOf(number) !== index);
    if (duplicate !== undefined) {
      console.log(`  ✗ Sélection en double interdite : ${duplicate}.`);
      continue;
    }

    tags = normalizeProductTags(numbers.map((number) => PRODUCT_TAG_ORDER[number - 1])).tags;
    if (tags.includes("promotion") && promotionDiscountPercent(price, compareAtPrice) === null) {
      console.log(
        "  ✗ Le tag « promotion » requiert un prix barré entier supérieur au prix et une remise d'au moins 1 %."
      );
      for (;;) {
        const answer = (await rl.question("  Prix barré valide en MAD : ")).trim();
        const number = Number(answer);
        if (Number.isInteger(number) && promotionDiscountPercent(price, number) !== null) {
          compareAtPrice = number;
          break;
        }
        console.log(`  ✗ Entier supérieur à ${price} produisant au moins 1 % de remise attendu.`);
      }
    }
    break;
  }

  const product = {
    slug,
    name: productName,
    tagline,
    price,
    compareAtPrice,
    collections,
    colorways,
    description,
    fabricRef: fabricAnswer === "",
    fabricValue: fabricAnswer || context.fabricDefault,
    careRef: careAnswer === "",
    careValue: careAnswer || context.careDefault,
    crossSellIds,
    tags,
  };

  console.log("\n── 11/11 · Récapitulatif ──");
  printRecap(product);

  const confirmed = await askYes(rl, "\nTout est correct ? (y/N) : ");
  rl.close();
  if (!confirmed) {
    console.log("Annulé — rien n'a été écrit.");
    return;
  }

  await runPipeline(context, product);
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.some((arg) => ["capabilities", "list", "show", "add", "edit", "delete", "--json", "--dry-run", "--expected-revision"].includes(arg))) {
    await runManagementCli(ROOT, argv);
    return;
  }
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }
  const context = await loadContext();
  if (options.from) {
    await runFromMode(context, options);
    return;
  }
  await runInterview(context);
}

const isDirectExecution =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectExecution) {
  main().catch((error) => {
    if (process.argv.includes("--json")) console.error(JSON.stringify({ schemaVersion: 1, error: error.message }));
    else console.error(error);
    process.exit(1);
  });
}
