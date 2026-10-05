---
name: product-page-marketing-sections
description: Creates beautiful, polished, persuasive mobile-first marketing sections for an existing product page from a user-provided strategy. Adapts or invents layouts and styles for the product and brand; bundled recipes are optional inspiration, never mandatory templates. Use when asked to add product-page sales sections, turn a marketing strategy into product-page content, or add image-led benefit, proof, or how-it-works sections. Usually selects 1–3 sections with one coherent visual direction, implements scoped responsive components, and preserves variants, cart, checkout, forms, pricing, analytics, and store behavior. Desktop receives a simple readable adaptation. Not for whole-store redesigns, standalone landing pages, catalog changes, or marketing strategy generation alone.
---

# Product Page Marketing Sections

The first purpose is to create beautiful, polished, persuasive marketing sections that bring the user's strategy to life on an existing product page. Design for the product, brand, and audience, with mobile quality first and a simple desktop adaptation. The bundled recipes are inspiration only: adapt, mix, or invent layouts and styles, including a coherent direction outside the library. Success means compelling, accessible sections with truthful claims and an intact buying flow, not an exact recipe match.

## Defaults and inputs

Use the current repository and conversation first. Normally the user supplies a strategy and a product identifier, URL, or route. Accept a strategy in prose, bullets, a document, or a referenced local file.

Infer from the repository when available:
- Product facts, actual options, language, audience, existing media, price source, and policies.
- Framework, component conventions, styling system, image pipeline, test commands, and route structure.
- Suitable insertion point and the existing purchase/form anchor or action.

Automatically choose the number, order, composition, and placement of sections. Default to the smallest useful set, often 1–3 sections; this is not a fixed cap. Do not turn every strategy into a complete sales page or duplicate information already well covered. Explicit user placement or section-count instructions take precedence.

Proceed without an approval loop when the target and essential information are clear. Ask a focused question only for a real blocker: ambiguous target product, missing strategy with no actionable angle, or a critical fact/asset that cannot be recovered. If a desired proof section lacks evidence, select a useful factual demonstration instead when the strategy permits it; do not invent proof or stop all independent work.

Use the page's language unless the user specifies another. Treat the user's wording “desktop vue/view” as viewport design, not a request to migrate the app to Vue.

## Workflow

**Efficient default:** discover the target narrowly, choose usually 1–3 sections and one coherent visual direction, read selected recipe snippets only if useful, implement, then run relevant checks. Expand investigation only for a concrete ambiguity or integration risk. Avoid broad repository research, agents, benchmarks, or multiple design variants unless justified by the task or explicitly requested. This is a workflow preference, not a token or time guarantee.

### 1. Establish the page boundary

Read project instructions and inspect version-control status where available. Preserve unrelated work. Start with the supplied route/product identifier; inspect its page, direct components, relevant product data/assets, and project scripts. Identify whether its template is shared. Broaden searches only when these do not resolve the target or insertion point.

Trace the relevant purchase mechanism: selected option, quantity, price, availability, form validation, cart action, tracking, and navigation. Record relevant baseline behavior using existing tests or a local browser when practical. Use the integration contract below; consult only needed parts of `references/integration-and-qa.md` for unfamiliar wiring or additional QA detail. Do not submit a real order.

Choose a normal document-flow insertion, usually after the purchase summary or between existing informational sections. The original purchase controls should remain easy to reach. Scope rendering to the requested product through the existing data/slot mechanism; do not accidentally inject the addition into every product.

### 2. Translate the strategy into sections

Form a brief internal or user-visible implementation note. Consult `references/strategy-to-sections.md` only if selection, ordering, or evidence handling needs clarification:

> Target: [product route]. Strategy: [angle]. Main hesitation: [question]. Add [sections] at [location]. Use [supported facts and existing or useful new assets]. Direction: [brief visual concept; optional recipe inspiration]. CTA: [existing destination, if needed].

The user supplied a strategy; implement it instead of substituting a generic marketing plan. Connect every section to a buying question. For each claim, identify the supplied or repository-backed fact supporting it. Do not add fictitious testimonials, review counts, discounts, deadlines, certifications, guarantees, or result imagery to imitate a template.

### 3. Select the composition

Choose a beautiful, polished composition that makes the strategy persuasive for this product and brand. Adapt or mix optional recipes, or invent a new coherent direction outside the library; no recipe or visual family must be matched. When inspiration is useful, search headings in `references/design-library.md` and use bounded reads for selected entries. Consult visual families or supporting techniques only for a specific design need. Do not load all references by default. The bundled inspiration is self-contained and requires no external design-source lookup.

Choose hierarchy, image-to-copy proportions, shapes, and spacing rhythm deliberately, adapting them to current product assets and brand colors. A composition is not evidence of a claim or conversion performance.

### 4. Implement the addition

Build actual HTML/component content in the existing stack, not a flattened screenshot of an entire section. Keep text, headings, buttons, and lists accessible and responsive. Reuse existing asset handling and local media. For new requested image processing, use the project's pipeline or an applicable image skill.

Add appropriate assets when they improve the composition: create lightweight decorative SVG/CSS graphics or accurate diagrams, or source suitable licensed lifestyle/product-support imagery when tools are available. Keep sourcing narrow and use the existing asset pipeline without unnecessary dependencies. Factual product depictions must faithfully reflect the actual product and verified features; testimonials and evidence must be authentic. Stock or decorative imagery may establish context, never customer proof or an unverified product capability. Do not invent product features, image URLs, or final placeholder cards, or claim an image was generated or sourced unless it actually was. If essential media is missing, ask for it or implement an honest alternative and disclose the limitation.

Use a component or template partial whose CSS is isolated. Keep content data separate when the project already does so. Prefer static/server-rendered markup unless a genuine interaction requires client state. Do not add a dependency for decoration, scrolling, icons already available in the repo, or a simple FAQ.

If another frontend skill is needed, retain this skill's mobile priority, strategy-led visual quality, and additive scope. Use its creative guidance where it fits the product and brand; avoid generic layouts or expanding into a complete storefront redesign.

## Mobile art direction

Design the phone layout first at approximately 390px, then check 360px and 430px; check narrower widths when the store supports them. Visual quality comes from compositions, not just colorful rounded cards:
- Prominent benefit headline with short readable lines.
- Large, purposeful demonstration/lifestyle/detail imagery.
- Short text tightly associated with the corresponding visual.
- Color-block panels, circular photographic crops, numbered steps, callouts, comparisons, or illustrative sequences selected for the strategy.
- A clear vertical story: question → explanation → evidence → reassurance/action, using only the parts needed.
- One coherent section palette drawn from brand/product colors. Reserve a distinct treatment for actions.

Suggested starting values, adjusted to existing typography and language:
- Outer gutters: 16–20px; section spacing: 28–48px; card padding: 16–24px.
- Main section heading: roughly 26–34px; body copy: 16–18px; comfortable Arabic line-height around 1.65–1.9.
- One column for substantial explanations. Two columns for brief photographic comparisons or compact 2×2 grids when readable. Use three columns only for very short icon labels that fit at 360px.
- Approximately 44px or larger touch areas for controls, visible keyboard focus, and sufficient contrast.
- Fluid image widths with intrinsic dimensions/aspect ratios. Preserve the important part of the demonstration when cropping.

These are starting points, not a global design-token rewrite. Use existing fonts with suitable language support. Avoid low contrast, crowded text, huge empty tails, incomplete panels, and decorative interference.

For desktop, reuse the same semantic content and DOM. Center within the current page width, constrain oversized illustrations and text, and optionally convert a suitable image/text pair to two columns. Avoid stretching a narrow poster across the whole monitor. Do not build a second elaborate desktop version or duplicate the purchase form for different breakpoints.

For Arabic/RTL, inherit page direction or set it on the new localized wrapper. Use logical spacing, intentional step order, and bidirectional isolation for model names, units, and prices. Keep English/French pages in their natural reading direction.

## Integration contract

The only authorized changes are the new marketing sections, scoped assets/styles, and the minimum integration needed to render them on the target page.

- Preserve the existing header, footer, gallery, purchase panel, option selection, quantities, inventory, prices, cart, checkout, order validation, tracking, consent behavior, and routing.
- Do not alter APIs, schemas, catalog records, global CSS resets, shared design tokens, payment/shipping logic, dependencies, or unrelated components for this task.
- Never replace a functional page with a visual mockup. Do not wrap the existing purchase subtree in a new client boundary or remount it through changing keys/layout branches.
- Keep new CSS under a local module or unique wrapper such as `.pdp-marketing-[slug]`; no unscoped `button`, `img`, `section`, `body`, `:root`, or universal selectors.
- New order prompts should normally be normal anchor links to the existing purchase controls. Preserve option selection; account locally for a fixed header and reduced-motion preferences. Add a stable target ID only if needed and safe.
- If a real add-to-cart button is explicitly required, reuse the existing component/action and state contract; do not simulate clicks or reconstruct the cart API.
- Do not create nested forms, duplicate IDs, fake buttons, independent checkout forms, synthetic commerce events, or global event handlers. No new sticky/floating purchase UI unless explicitly requested.
- Product prices/offers shown in the addition must use the current source of truth, including variant changes. If that requires invasive logic, omit the redundant price and link to the existing purchase block instead.
- Render only on the intended product unless the user explicitly asks for a shared section. Check another product when touching a shared template.
- If preserving behavior is impossible with the proposed insertion, choose a less invasive placement or explain the actual blocker. Do not silently expand scope.

## Verification and delivery

Run applicable project checks (typecheck, lint, build, or targeted tests according to project scripts) and inspect the rendered target page if browser tooling is available. Load the browser skill applicable to the tool being used. The detailed QA reference is optional; the checks here still apply.

Capture/review mobile screenshots against the chosen composition, checking hierarchy, image crops, text readability, overflow, RTL where applicable, and unobstructed controls at the widths above. Check a representative desktop viewport, keyboard focus, and new console errors too. Exercise relevant variant/price/availability, quantity, cart/form validation, and new CTA behavior in a local/test environment without placing an order; confirm the CTA preserves selection and sections introduce no duplicate commerce events or mutations. When a shared template changes, confirm an unrelated product is unaffected.

Fix issues caused by the addition and review the final diff for unintended scope changes. If browser execution or a backend is unavailable, run possible checks and clearly state what remains unverified. Do not claim rendered mobile quality or purchase-flow preservation based only on a code review.

Final handoff, concise:
1. Sections added and how they serve the strategy.
2. Target page and main changed files.
3. Mobile visual direction and simple desktop treatment.
4. Checks actually performed and any blockers.

Do not claim a conversion increase without measurement. No commits, deployments, or live orders unless separately requested.

## References

- `references/design-library.md`: 26 optional inspiration recipes; search headings and read selected snippets only when useful.
- `references/strategy-to-sections.md`: optional selection, ordering, and evidence guidance.
- `references/integration-and-qa.md`: optional integration details and expanded verification checklist.
