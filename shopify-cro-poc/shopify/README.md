# Shopify integration (CRO contextual hero)

This folder connects your **Shopify storefront** to the PoC FastAPI service (`POST /decide`, `POST /feedback`).

## What gets sent to the API

| Signal | Source |
|--------|--------|
| `device_type` | `matchMedia('(max-width: 768px)')` |
| `traffic_source` | `utm_source` query param (mapped to `meta`, `google`, … or raw) |
| `is_returning` | Liquid: `{% if customer %}` |
| `locale` | `request.locale.iso_code` |
| `template` | `template.name` |
| `utm_campaign` | Optional theme setting, or extend the JS to read `utm_campaign` from the URL |

The **hero copy** (headline, subtitle, CTA label, trust pills, `variant-a/b/c` styling) comes from the API response.

## Requirements

1. **HTTPS API** on a public URL (Shopify storefronts are `https://`; browsers block `http://localhost` from the live theme).
2. **CORS**: the backend already allows `allow_origins=["*"]`. For production, narrow this to your shop domain(s).
3. Theme **2.0** (JSON templates) recommended.

## Option A — Manual theme install (fastest PoC)

1. In **Online Store → Themes → Edit code**, upload to **Assets**:
   - `shopify/storefront/cro-hero-banner.js`
   - `shopify/storefront/cro-hero-banner.css`
2. Under **Sections**, create `cro-hero-banner.liquid` and paste the contents of  
   `shopify/theme/sections/cro-hero-banner.liquid`.
3. In **Customize theme**, add section **“CRO contextual hero”** to the homepage.
4. Set **CRO API base URL** to your deployed API, e.g. `https://cro-api.yourdomain.com` (no trailing slash).

### Local dev against a live dev theme

Use a tunnel (Cloudflare Tunnel, ngrok, etc.) so `https://xxxx.trycloudflare.com` points to `localhost:8000`, then paste that origin as the API base URL.

## Option B — Theme app extension (Shopify CLI app)

1. Create or open a **Shopify app** with CLI (`shopify app init`).
2. Copy the folder  
   `shopify/theme-app-extension/cro-contextual-hero/`  
   into your app as  
   `extensions/cro-contextual-hero/`  
   (merge `shopify.extension.toml` + `blocks/` + `assets/`).
3. Run `shopify app dev`, install the app on a dev store.
4. In the theme editor, add the **CRO contextual hero** app block to a section.

See [Theme app extensions](https://shopify.dev/docs/apps/build/online-store/theme-app-extensions).

## Option C — App proxy (optional, production-hardening)

To avoid exposing your API origin in the theme and to verify requests with Shopify’s HMAC:

1. In the Partner Dashboard, configure **App proxy** (e.g. prefix `apps/cro`, subpath `proxy`).
2. Point the proxy to your backend.
3. Change the storefront JS `apiBase` to the proxy URL and add verification in FastAPI.

This PoC does **not** implement app-proxy signing yet.

## Rewards (clicks)

The script sends **`reward: 1`** on primary CTA click and best-effort **`reward: 0`** on `pagehide` via `sendBeacon`. For **purchase** or **add-to-cart** rewards, extend the theme (additional script on cart/checkout) to call `POST /feedback` with the same `decision_id` you stored in `sessionStorage` or a cookie when the hero rendered.

## Files

| Path | Role |
|------|------|
| `storefront/cro-hero-banner.js` | Storefront logic |
| `storefront/cro-hero-banner.css` | Variant styling |
| `theme/sections/cro-hero-banner.liquid` | Copy-paste section |
| `theme-app-extension/cro-contextual-hero/` | CLI extension scaffold |
