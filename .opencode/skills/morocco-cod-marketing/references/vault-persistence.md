# Vault and persistence

## Paths and live sources

- Vault root: `/home/tal7a/Work/MARKETING_VAULT`
- Template: `00 Templates/Product Template.md`
- Table: `02 Bases/Products_Marketing.base`
- Product notes: `01 Products`
- Images: `03 Assets/Product images`

Read the template and the table before presenting choices or writing. Treat
template list entries as choice catalogs, never as all-selected product
defaults. Reread the template immediately before every choice presentation
and every write. Verify destination parent directories before creating any
note or asset.

## Exact-key mapping

Use the live keys exactly as they appear, including emojis, spaces and
existing spelling (e.g. `benifits`, `audiance`). If live keys change,
reconcile with the current template and ask about renamed keys rather than
inventing them. Never silently introduce parallel properties or a new
schema.

| Checkpoint | Live property keys (exact) |
|---|---|
| Essentials | `🛫 find_product_methods`, `🛫 categories`, `🛫 assets`, `cover` |
| Research | `✈️Reputation_Reviews_Mining`, `✈️Concurrences_Analyses` |
| Direction | `🎡Problems_defaut_pain_point`, `🎡solution_feature_benifits_special_Competitive_advantage`, `🎡targeted_audiance_pain_point_benifits`, `🚂human_desir_Angle_marketing`, `🚂emotion_angle`, `🚂Copy_Techniques` |
| Package | `🌟Creative_Typee_Techniques`, `🌟Hook_Type`, `🌟Action_plan` |
| Always preserved | `📝NOTES`, unrelated properties and manual body text |

- List properties: write only exact approved labels from the live catalog,
  never all available choices. Preserve catalog spelling and emojis.
- Text properties: write a concise approved summary as a valid YAML string.
- `🛫 assets` describes sourcing/production plans; never store a cover link
  in it.

## Body sections

Write detailed reasoning into named body sections; keep properties concise.

New sections used by this skill:

- `## Workflow progress` — checkpoint statuses (`pending`, `approved`,
  `skipped`, `needs-review`), market, analysis/ad/prompt languages,
  confirmed facts, decisions, cover status, and the next step/question.
- `## Research notes` — sources, quote versus paraphrase, objections and
  competitor notes; evidence kept separate from interpretation.
- `## Strategy direction` — the approved direction in full.
- `## Ad package — Static` and `## Ad package — Video` — the approved
  creative package.
- `## Product-page brief` — the handoff for the user's design skill.
- `## Results review` — findings from a results-review session.

Legacy step sections from older notes (e.g. `## 09 — Audiences`,
`## 15 — Ad/action plan`) stay readable sources: use them when resuming an
old note, and keep a concise per-step summary there when the notes already
follow that structure, so the table and older workflows remain coherent.

## Save contract

1. Reread the live note and template immediately before saving; compare
   with the version used for drafting. Detect concurrent edits; preserve
   unrelated edits and ask about conflicting ones.
2. Persist each approval immediately, before asking the next question;
   never defer to an end-only save.
3. Apply small targeted patches to matching properties and owned body
   sections only. Do not rewrite the whole note through generic
   serialization that loses formatting.
4. Parse YAML before and after the patch: reject duplicate keys; verify
   exact live schema keys, strings versus arrays, approved values, and any
   quoted cover link's existing vault path. Keep unrelated inherited keys;
   flag schema drift rather than deleting or inventing keys.
5. Reread after writing and verify the intended changes plus preservation
   of unrelated content. Only then say "saved" with the note path and what
   was approved; report failures accurately.
6. If a save or validation fails, stop advancing and resolve that save
   without clobbering newer edits. A proposed patch is not a saved note;
   disclose any validation tools that are unavailable.

## Revision cascade

If an upstream decision changes (audience, angle, offer, language), show
the impact and mark affected downstream sections `needs-review`, retaining
their content until separately approved revisions are ready. The ad package,
video scripts and page brief all depend on the approved direction.

## Cover handling

- Propose a specific product image during essentials if needed; when a page
  offers several candidates, ask which to use.
- Only after approval, copy or download the image into
  `03 Assets/Product images`, preserving the source. Reuse an existing
  vault image without duplication.
- Use `image-to-webp` when conversion is appropriate and that skill is
  available; keep the source when converting.
- Confirm the destination exists, then set a safely quoted, vault-relative
  wikilink: `cover: "[[03 Assets/Product images/example.webp]]"`.
- On failure, retain the prior link or an empty value and report the actual
  failure.

## Resume rules

- Reread note, template and table; use recorded progress, not populated
  fields alone, to identify approvals; resolve ambiguity with the user.
- Ask resume versus revise unless already answered. Distinguish skipped
  from pending work; preserve manual changes and filled research.
- Resume at the next pending or `needs-review` checkpoint decision.
- Older notes created by a previous version of this workflow may hold
  inherited all-options lists with no recorded approval; treat those as
  unfilled expectations, not approved selections, and continue with the
  three-checkpoint flow from the recorded progress.