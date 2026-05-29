---
name: meta-pixel-capi
description: Implement Meta (Facebook) Pixel tracking with Conversions API (CAPI) for dual-channel event deduplication. Covers browser pixel setup, server-side CAPI integration, eventID deduplication architecture, standard event mapping, PII hashing, and debugging. Use when the user is adding Meta Pixel tracking, setting up CAPI, implementing event tracking for ads, debugging pixel/CAPI issues, or mentions Meta Pixel, Facebook Pixel, Conversions API, fbq, pixel tracking, or ad conversion tracking.
---

# Meta Pixel + CAPI Implementation

## When to Use

Use this skill when the user:
- Is implementing Meta Pixel tracking on a website (any framework)
- Is setting up server-side Conversions API (CAPI) for deduplication
- Is debugging Pixel or CAPI issues (events not firing, duplicates, missing data)
- Mentions Meta Pixel, Facebook Pixel, `fbq`, CAPI, or conversion tracking
- Needs to add standard events (PageView, ViewContent, AddToCart, Purchase, etc.)
- Is implementing e-commerce tracking with Meta

## Architecture: Dual Channel Deduplication

Every tracked event fires through **both** channels with the **same eventID**:

```
User action
  ├─ Browser: fbq('track', 'EventName', {params}, {eventID: 'uuid'})
  └─ Server:  POST /api/pixel → Meta Graph API /events {event_id: 'uuid', ...}
                                         ↑
              Meta matches by (event_name + event_id) → deduplicates
```

**The eventID must be:**
- A unique UUID (use `crypto.randomUUID()` on frontend)
- Identical on both browser and server channels for the same event
- Passed as **4th argument** to `fbq()` (NOT inside params — see Bug 2)
- Sent as `event_id` in the CAPI payload

## Critical Bugs to Avoid

### Bug 1: CAPI endpoint URL mismatch

Frontend calls `${BASE_URL}/pixel` but backend route is at `/api/pixel`. Always verify the full constructed URL matches the backend route. Check how the base URL is used across the app before constructing API URLs.

**Rule:** Open DevTools → Network tab and verify the exact URL the frontend requests. Match it to the backend route definition.

### Bug 2: eventID in wrong position for fbq()

Meta **ignores** `eventID` when it's inside the params object. It MUST be the 4th argument:

```js
// CORRECT — eventID as 4th argument
fbq('track', 'Purchase', { value: 100, currency: 'USD' }, { eventID: 'uuid' })

// WRONG — eventID inside params, Meta ignores it
fbq('track', 'Purchase', { value: 100, currency: 'USD', eventID: 'uuid' })
```

### Bug 3: Access token not scoped to the pixel

Tokens generated from **Business Settings → System Users** do NOT have pixel-level permissions. Error: `Object with ID 'xxx' does not exist`.

**Fix:** Generate the token from **Events Manager → select pixel → Settings → Conversions API → Generate Access Token**. This ensures the token is scoped to the exact pixel with `events` endpoint permission.

### Bug 4: Missing user data in CAPI events

Error: `error_subcode: 2804050` — "You haven't added sufficient customer information parameter data."

Every CAPI event MUST include at minimum:
- `client_ip_address`
- `client_user_agent`

Purchase events should additionally include hashed `ph` (phone), `fn` (first name), `ln` (last name), `ct` (city) for better match rates.

### Bug 5: Duplicate PageView from inline script

Adding `fbq('track', 'PageView')` after `fbq('init')` in the inline script fires a PageView **without eventID**. If your app also fires PageView via `useEffect` (with eventID), you get duplicate PageViews where the inline one cannot be deduplicated.

**Fix:** Only call `fbq('init')` in the inline script. Let your app's `trackPageView()` function handle all PageViews with eventID. The `fbq` stub correctly queues and replays all 4 arguments including `{eventID}` — timing is not an issue.

**Note:** Facebook's Test Events panel often does NOT display `event_id` for browser PageView events, even when correctly sent. This is a known platform quirk. Verify by checking DevTools → Network → filter `tr?` → inspect the `eid` parameter in the request payload.

### Bug 6: Using trackCustom for standard events

`fbq('trackCustom', 'PageView', ...)` sends PageView as a **custom event** — Meta handles standard and custom events differently. Custom events don't appear in the standard Events dashboard, lose `eid` parameter intermittently, and deduplication with CAPI fails.

```js
// CORRECT
fbq('track', 'PageView', params, { eventID })         // Standard event → 'track'
fbq('track', 'ViewContent', params, { eventID })       // Standard event → 'track'
fbq('trackCustom', 'SignUpCompleted', params, { eventID }) // Custom event → 'trackCustom'

// WRONG
fbq('trackCustom', 'PageView', params, { eventID })    // Standard event with trackCustom!
```

**Rule:** Use `'track'` for all Meta standard events. Only use `'trackCustom'` for events NOT in Meta's standard event list.

### Bug 7: Over-engineering PageView timing

Using `waitForFbq()` polling, `onLoad` callbacks, or `useState(pixelReady)` to delay PageView until the pixel script loads causes PageView to not fire at all or fire too late. `onLoad` doesn't work with `dangerouslySetInnerHTML`.

**Fix:** Use the simplest approach — `useRef(firstRender)` with `useEffect([pathname])`. The `fbq` stub queues calls and correctly replays them with all 4 arguments. Do NOT wait for the script to load.

```tsx
const firstRender = useRef(true);
const previousPathname = useRef(pathname);

useEffect(() => {
  trackPageView(url, title);  // fbq stub queues this, replays when real fbq loads
  if (firstRender.current) {
    firstRender.current = false;
    return;
  }
  if (previousPathname.current !== pathname) {
    previousPathname.current = pathname;
    trackPageView(url, title);
  }
}, [pathname]);
```

### Bug 8: Redundant fbc/fbp in trackPurchase

Don't pass `fbc`/`fbp` as `userData` to `sendCapiEvent()` — it already fetches them internally. If the caller passes them via spread and the cookies don't exist, `undefined` overwrites the internally-fetched values, removing them from the payload. `fbc`/`fbp` improve match quality but are not required.

## fbq() Call Format

### Argument positions (MUST follow exactly)

```
fbq('track', 'EventName', { params }, { eventID: 'uuid' })
//   arg1       arg2        arg3         arg4 (dedup info object)
```

### Standard vs Custom

| Event type | Command | Examples |
|-----------|---------|----------|
| Standard | `'track'` | PageView, ViewContent, AddToCart, InitiateCheckout, Purchase, Lead, Search, Contact, SubmitApplication |
| Custom | `'trackCustom'` | Any event name NOT in Meta's standard list |

Using `'trackCustom'` for standard events causes: `eventID`/`eid` lost intermittently, events missing from standard dashboard, CAPI deduplication breaks.

### How the fbq queue works

The Meta pixel snippet creates a stub that queues calls before the real script loads. This queue **correctly preserves all 4 arguments** including `{eventID}`. When the real `fbq` loads, it replays the queue. The only thing that breaks eventID is putting it in the wrong position (Bug 2), not timing.

## CAPI Event Requirements

### Minimum required fields (every event)

| Field | Source | Required |
|-------|--------|----------|
| `event_name` | Fixed string | Yes |
| `event_time` | Unix timestamp (seconds) | Yes |
| `event_id` | UUID (same as browser event) | Yes |
| `action_source` | `"website"` | Yes |
| `event_source_url` | Current page URL | Recommended |
| `client_ip_address` | Extracted from request headers | Yes (or CAPI fails) |
| `client_user_agent` | Extracted from request headers | Yes (or CAPI fails) |

### Additional fields for Purchase events (improves match rate)

| Field | Source | Hashing |
|-------|--------|---------|
| `ph` | Customer phone | SHA256, lowercase, trimmed |
| `fn` | Customer first name | SHA256, lowercase, trimmed |
| `ln` | Customer last name | SHA256, lowercase, trimmed |
| `ct` | Customer city | SHA256, lowercase, trimmed |
| `external_id` | Phone number (unique ID) | SHA256, lowercase, trimmed |
| `fbc` | `_fbc` cookie (click ID) | Raw, no hashing |
| `fbp` | `_fbp` cookie (browser ID) | Raw, no hashing |

### Hashing rules

All PII must be SHA256-hashed before sending to Meta:

```python
import hashlib

def sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
```

```javascript
async function sha256(value: string): Promise<string> {
  const msgBuffer = new TextEncoder().encode(value.trim().toLowerCase());
  const hashBuffer = await crypto.subtle.digest("SHA-256", msgBuffer);
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
```

- Lowercase + trim BEFORE hashing
- `fbc` and `fbp` are NOT hashed (already Meta-generated IDs)

## Standard Events Reference

| Event | Browser | CAPI | Parameters | Trigger |
|-------|:-------:|:----:|------------|---------|
| PageView | Yes | Yes | `page_title`, `page_location` | Every page navigation |
| ViewContent | Yes | Yes | `content_ids`, `content_name`, `content_type`, `currency`, `value` | Product/details page |
| AddToCart | Yes | Yes | `content_ids`, `content_type`, `currency`, `value`, `num_items` | Add to cart |
| InitiateCheckout | Yes | Yes | `content_ids`, `contents`, `content_type`, `currency`, `value`, `num_items` | Checkout start |
| Purchase | Yes | Yes | `content_ids`, `contents`, `content_type`, `currency`, `value`, `num_items` | Order confirmation |

### Parameter format

```js
content_ids: ['product-slug-1']    // Array of strings (product IDs/slugs)
content_type: 'product'            // Always 'product' for e-commerce
currency: 'USD'                    // ISO 4217
value: 29.99                       // Number (total price)
num_items: 2                       // Number
contents: [{ id: 'variant-1', quantity: 1, item_price: 29.99 }]  // Array for Purchase
```

## Environment Variables

### Frontend

| Variable | Notes |
|----------|-------|
| `NEXT_PUBLIC_FACEBOOK_PIXEL_ID` | Must be in BOTH build args and runtime env vars for Next.js |

For Next.js Docker deployments, declare in Dockerfile:

```dockerfile
ARG NEXT_PUBLIC_FACEBOOK_PIXEL_ID
ENV NEXT_PUBLIC_FACEBOOK_PIXEL_ID=$NEXT_PUBLIC_FACEBOOK_PIXEL_ID
```

### Backend

| Variable | Notes |
|----------|-------|
| `FACEBOOK_PIXEL_ID` | Same pixel ID as frontend |
| `FACEBOOK_ACCESS_TOKEN` | From Events Manager → Settings → Conversions API (NOT Business Settings) |
| `FACEBOOK_TEST_EVENT_CODE` | Set during testing, **remove in production** |
| `FACEBOOK_API_VERSION` | Defaults to `v22.0` |

## Testing Flow

### 1. Set test event code

Add `FACEBOOK_TEST_EVENT_CODE=TEST12345` to backend env vars. Events go to the Test Events tab (not production data).

### 2. Hit the test endpoint

Create a test endpoint that sends a CAPI event and returns the full response. Expected:

```json
{
  "pixel_id": "YOUR_PIXEL_ID",
  "api_version": "v22.0",
  "result": { "success": true, "data": { "events_received": 1 } }
}
```

### 3. Check Meta Test Events tab

Events Manager → pixel → Test Events. You should see:
- **Browser** events (connection: "Browser") — should have `eventID`
- **Server** events (connection: "Server") — should have `event_id`
- Both with matching IDs for deduplication

### 4. Verify eventID in browser events

DevTools → Network → filter `tr?` → check payload for `eid` parameter. It must match the server event's `event_id`. If `eid` is missing: check that eventID is the 4th argument to `fbq()` (Bug 2) and that you're using `'track'` not `'trackCustom'` for standard events (Bug 6).

### 5. Remove test code for production

Delete `FACEBOOK_TEST_EVENT_CODE` or set to empty string when done.

## CAPI Error Codes

| Code | Subcode | Meaning | Fix |
|------|---------|---------|-----|
| 100 | 33 | Object doesn't exist / missing permissions | Wrong pixel ID or token not scoped. Regenerate from Events Manager → Settings → Conversions API |
| 100 | 2804050 | Insufficient customer info | Add `client_ip_address` + `client_user_agent` at minimum |
| 100 | — | Invalid parameter | Check parameter format (arrays, numbers, etc.) |
| 190 | — | Invalid access token | Token expired/wrong. Regenerate from Events Manager |

## Debugging Checklist

- [ ] `NEXT_PUBLIC_FACEBOOK_PIXEL_ID` set in both build args AND runtime env vars
- [ ] `FACEBOOK_PIXEL_ID` and `FACEBOOK_ACCESS_TOKEN` set in backend env vars
- [ ] Access token from Events Manager → Settings → Conversions API (NOT Business Settings → System Users)
- [ ] CAPI endpoint URL matches backend route exactly (verify in DevTools Network tab)
- [ ] `eventID` is 4th argument to `fbq()`: `fbq('track', 'Event', params, {eventID})`
- [ ] Using `'track'` not `'trackCustom'` for all standard events (PageView, ViewContent, etc.)
- [ ] `event_id` in CAPI payload matches browser event's eventID
- [ ] `client_ip_address` and `client_user_agent` included in every CAPI event
- [ ] PII fields (ph, fn, ln, ct) are SHA256-hashed, trimmed, lowercased
- [ ] `fbc`/`fbp` cookies sent from browser to backend (optional but improves matching)
- [ ] Test endpoint returns `events_received: 1`
- [ ] DevTools Network tab → filter `tr?` → `eid` parameter present in browser events
- [ ] `FACEBOOK_TEST_EVENT_CODE` removed for production
- [ ] CORS allows frontend domain for the CAPI endpoint
- [ ] Inline pixel script has ONLY `fbq('init')` — no `fbq('track', 'PageView')` after it (Bug 5)
- [ ] PageView uses simple `useRef(firstRender)` pattern, NOT `waitForFbq` or `useState(pixelReady)` (Bug 7)
- [ ] `undefined` values stripped from params before sending to `fbq()` and CAPI
- [ ] PageView eventID verified via DevTools Network → `tr?` → `eid` (NOT Test Events panel, which hides it sometimes)
