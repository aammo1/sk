# Integration and verification

## Before editing

Inspect project instructions, repository status, target route, template, product data, styles, and relevant tests. Identify whether the page is server-rendered, client-rendered, or platform-templated. Reuse its architecture.

Record only what is relevant to the insertion:
- Target product identity and route.
- Shared template scope and existing product-specific slot/data mechanism.
- Existing purchase form/anchor and fixed header height if applicable.
- Variant, quantity, price, stock, and cart/order action ownership.
- Form nesting boundaries and accessible heading structure.
- Existing analytics integration so new content does not interfere with it.
- Initial mobile layout and behavior when browser access is available.

Do not log customer data, tokens, or secrets as part of this inspection.

## Minimal implementation boundary

Preferred change shape:
1. A product-specific marketing component or partial.
2. Scoped style module or styles under a unique wrapper.
3. Necessary optimized media, if not already present.
4. A minimal import/render call or existing content-slot entry on the target page.

Use the repository's versioned content mechanism where relevant. Do not change a shared product schema or database to add a one-off section if an existing extension point or local component suffices.

### Shared templates
Scope by the stable product identity already used by the app. Avoid brittle URL-substring matching. Check a non-target product after shared-template integration. If the user requests reusable sections for multiple products, make that scope explicit and follow existing content conventions.

### CSS isolation
- Use a CSS module or unique wrapper and local variables.
- Keep resets and variables out of global `:root`, `body`, and shared token definitions.
- Avoid global `overflow-x: hidden` as a fix for section overflow; fix the overflowing element.
- Avoid layout shifts with image dimensions and stable content.
- Keep decorations noninteractive (`pointer-events: none` where appropriate), out of the accessibility tree, and behind text/controls.
- Do not introduce overlays or large z-index values that obstruct checkout or existing sticky elements.
- Prefer normal flow, flex, or grid. Absolute positioning belongs to local decoration, not the main paragraph layout.

### Purchase prompts
Default to a real anchor pointing at existing purchase controls. Add an ID only if missing, unique, and safe. Adjust target scroll margin locally for the actual header. Do not change page-wide scroll behavior for one CTA. If script-assisted focus/scrolling is genuinely needed, keep it local, accessible, and compatible with reduced motion.

Never add nested forms or an independent second form. Do not simulate a click on a hidden button or copy/paste order code. Preserve selected variant/quantity and current price. Avoid synthetic analytics calls for navigation-only CTAs; follow the existing tracking convention only when needed.

### Framework adaptations
- **React / Next.js:** preserve current component boundaries and keys; prefer a static/server component. Keep the purchase subtree in place. Use the existing image component. Do not turn the page into a client component for decorative interactions.
- **Vue / Nuxt:** use scoped styles and current props/content conventions. Do not create new duplicate stores or watchers for purchase state.
- **Shopify / Liquid or other templates:** use the existing section/snippet mechanism and scope the block to the target template/product. Keep variant form IDs and theme events intact.
- **Other stacks:** use their existing partial/component extension point. No framework migration.

## Verification checklist

### Automated checks
- Run relevant type checking, linting, build, or existing targeted tests according to project scripts.
- Do not add tests that merely mirror static markup. Add a focused regression test when integration creates a meaningful behavioral risk and the repo supports it.
- Note pre-existing failures separately from failures introduced by the addition.

### Mobile visual checks
Review screenshots at approximately 390px and verify 360px/430px layouts. Also test narrower widths if supported by the store.
- Headline has a readable hierarchy and intentional wrapping.
- Imagery is large enough to explain the benefit.
- Text matches the corresponding photo or diagram.
- Layout is polished, persuasive, and coherent for the product, brand, and strategy; assess visual quality rather than resemblance to a library recipe.
- No clipped text, overflowing grids, decorative obstruction, or horizontal scrolling.
- Comparisons and short two-column cards remain readable.
- Font and Arabic shaping are correct; RTL order and Latin units/prices are readable.
- Buttons are visibly actionable with adequate target sizes and focus styles.
- Existing fixed header/sticky purchase controls do not cover the section or its destination.

### Desktop check
Review at one representative desktop viewport (for example 1280px).
- Content is centered/constrained appropriately.
- No giant stretched phone-poster graphics.
- Long text has sensible line length.
- Optional two-column layout retains the intended sequence.
- Same DOM/content and purchase state are reused.

### Functional smoke check
Use a local preview or test environment and stop before a real order/payment.
- Existing variant change still updates the correct price/availability.
- Quantity selection and applicable limits behave as before.
- Existing cart action or order validation still works where testable.
- New CTA reaches the original purchase block without changing selection.
- No extra network mutations or duplicate commerce events from mounting/scanning sections.
- Keyboard navigation and focus remain sensible.
- A non-target product remains unchanged if a shared template was touched.
- No new console errors caused by the addition.

Do not assert a checklist item passed without actually checking it. If the backend, browser, or local preview cannot run, verify code and available tests, then state the specific remaining gaps.

### Diff review
Confirm edits are confined to the intended section and insertion. Check for accidental global style changes, dependency changes, catalog edits, checkout/form changes, unrelated formatting, duplicated IDs, and leftover placeholder assets.

## Completion standard

A section is complete when it communicates the chosen strategy, uses actual available facts/media, is visually checked where possible, and has no observed regression in the checks performed. Do not equate “build passed” with “all store functionality verified.”
