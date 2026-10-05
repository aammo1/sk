# Product Page Marketing Sections

A reusable skill whose first purpose is adding beautiful, polished, persuasive sections to an existing product page from your marketing strategy. Its 26 image-led recipes are optional inspiration, never mandatory templates: adapt, mix, or invent a coherent direction for the product and brand. Mobile comes first; desktop gets a simple responsive adaptation. Existing store functionality is preserved through scoped components, minimal integration, and relevant checks.

## Use

Ask your agent:

> Use product-page-marketing-sections on /products/travel-kit. My strategy is to show frequent travellers that it fits in a small bag and is easy to set up. Choose 1–3 sections and placement using our product photos and actual instructions. Prioritize large mobile imagery, bold short headings, and alternating numbered photo/text panels in our brand colors. Keep desktop simple and preserve the existing buying flow.

Optional input:
- Preferred visual style: soft cream lifestyle panels, bold contrasting photo bands, a monochromatic infographic, dark technical close-ups, or playful curved-arrow collage.
- Exact section count or insertion point.
- Photos, authentic reviews, demonstrations, or copy.
- Language and brand preferences.

The skill usually selects 1–3 sections and one coherent visual direction. It starts with the target page and directly relevant assets, facts, and purchase behavior, then reads selected recipe snippets only when useful. Strategy and detailed QA references are optional when needed. Relevant project/build, mobile, and purchase-state checks remain part of the workflow; the handoff identifies untested items. It asks only for essential missing information and avoids broad research or design variants unless justified or requested. No token or time budget is guaranteed.

## Files

- `SKILL.md`: executable workflow and scope.
- `references/design-library.md`: detailed reusable compositions and technique catalog.
- `references/strategy-to-sections.md`: marketing strategy mapping.
- `references/integration-and-qa.md`: non-invasive integration and verification.
- `evals/evals.json`: representative skill evaluation scenarios.

## Visual guidance

Bundled inspiration covers outcome spotlights, circular-photo benefit strips, annotated details, alternating image/text rows, numbered setup steps, factual comparisons, and more; new layouts and styles are welcome. Useful assets may include lightweight SVG/CSS decoration, accurate diagrams, or suitable licensed lifestyle/product-support imagery sourced with available tools. Product depictions must be faithful to the actual product, claims supported, and testimonials/evidence authentic; decorative imagery is never customer proof. Add no unnecessary dependencies or false claims of image generation.

## Installation

Place this folder, or a symlink to it, in the skills directory your agent discovers. On this machine the standard location is `~/.agents/skills/product-page-marketing-sections/`. Start a new agent session if the skill does not appear in an already-open session.

The skill does not include product-specific components; it builds them in the target project's own stack when invoked.
