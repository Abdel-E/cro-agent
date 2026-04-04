/**
 * CRO contextual hero — Shopify storefront
 *
 * Markup (see theme section): wrapper [data-cro-hero-mount] contains
 *   <script type="application/json" data-cro-hero-config>…</script>
 *   <div data-cro-hero-root>…</div>
 *
 * Config: apiBase, surfaceId, isReturning, locale, template, ctaUrl (absolute),
 * utmCampaign (optional), showDebug, fallbackHeadline, fallbackSubtitle
 */
(function () {
  "use strict";

  function parseTrafficSource() {
    try {
      var p = new URLSearchParams(window.location.search);
      var utm = (p.get("utm_source") || "").toLowerCase();
      if (!utm) return "direct";
      if (utm.indexOf("meta") !== -1 || utm.indexOf("facebook") !== -1 || utm.indexOf("fb") !== -1)
        return "meta";
      if (utm.indexOf("google") !== -1 || utm === "gclid") return "google";
      if (utm.indexOf("tiktok") !== -1) return "tiktok";
      if (utm.indexOf("email") !== -1 || utm.indexOf("newsletter") !== -1) return "email";
      return utm.slice(0, 32);
    } catch (e) {
      return "direct";
    }
  }

  function deviceType() {
    return window.matchMedia && window.matchMedia("(max-width: 768px)").matches
      ? "mobile"
      : "desktop";
  }

  function readConfig(root) {
    var mount = root.closest("[data-cro-hero-mount]");
    var el = mount ? mount.querySelector("[data-cro-hero-config]") : null;
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent.trim());
    } catch (e) {
      return null;
    }
  }

  function initRoot(root) {
    var cfg = readConfig(root);
    if (!cfg || !cfg.apiBase) {
      console.warn("[CRO Hero] Missing config or apiBase");
      return;
    }

    var apiBase = String(cfg.apiBase).replace(/\/+$/, "");
    var decideUrl = apiBase + "/decide";
    var feedbackUrl = apiBase + "/feedback";

    function post(url, body) {
      return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    }

    var surfaceId = cfg.surfaceId || "hero_banner";
    var ctaUrl = cfg.ctaUrl || "/";

    var headlineEl = root.querySelector("[data-cro-headline]");
    var subtitleEl = root.querySelector("[data-cro-subtitle]");
    var ctaEl = root.querySelector("[data-cro-cta]");
    var trustEl = root.querySelector("[data-cro-trust]");
    var debugEl = root.querySelector("[data-cro-debug]");
    var inner = root.querySelector(".cro-hero-inner");

    var activeDecision = null;
    var feedbackSent = false;

    function escapeHtml(s) {
      var d = document.createElement("div");
      d.textContent = s;
      return d.innerHTML;
    }

    function render(data) {
      var c = data.content || {};
      var style = c.style_class || "variant-a";
      if (inner) {
        inner.className = "cro-hero-inner " + style;
      }
      if (headlineEl) headlineEl.textContent = c.headline || "";
      if (subtitleEl) subtitleEl.textContent = c.subtitle || "";
      if (ctaEl) {
        ctaEl.textContent = c.cta_text || "Shop now";
        ctaEl.setAttribute("href", ctaUrl);
      }
      if (trustEl) {
        trustEl.innerHTML = (c.trust_signals || [])
          .map(function (s) {
            return '<span class="cro-trust-pill">' + escapeHtml(s) + "</span>";
          })
          .join("");
      }
      if (debugEl) {
        if (cfg.showDebug) {
          debugEl.textContent =
            "Variant " +
            data.variant_id +
            " · " +
            data.segment +
            " · p=" +
            (data.probability && data.probability.toFixed
              ? data.probability.toFixed(3)
              : data.probability);
          debugEl.hidden = false;
        } else {
          debugEl.hidden = true;
        }
      }
      root.style.display = "";
    }

    function decide() {
      feedbackSent = false;
      activeDecision = null;
      var context = {
        device_type: deviceType(),
        traffic_source: parseTrafficSource(),
        is_returning: !!cfg.isReturning,
        locale: cfg.locale || "",
        template: cfg.template || "",
      };
      if (cfg.utmCampaign) context.utm_campaign = cfg.utmCampaign;

      post(decideUrl, { surface_id: surfaceId, context: context })
        .then(function (data) {
          activeDecision = data;
          render(data);
        })
        .catch(function (err) {
          console.warn("[CRO Hero] decide failed", err);
          if (headlineEl) headlineEl.textContent = cfg.fallbackHeadline || "Shop our bestsellers";
          if (subtitleEl) subtitleEl.textContent = cfg.fallbackSubtitle || "";
          if (inner) inner.className = "cro-hero-inner variant-a";
          root.style.display = "";
        });
    }

    function sendFeedback(reward) {
      if (!activeDecision || feedbackSent) return;
      feedbackSent = true;
      post(feedbackUrl, {
        decision_id: activeDecision.decision_id,
        variant_id: activeDecision.variant_id,
        reward: reward,
      }).catch(function () {});
    }

    if (ctaEl) {
      ctaEl.addEventListener("click", function () {
        sendFeedback(1);
      });
    }

    window.addEventListener("pagehide", function () {
      if (!feedbackSent && activeDecision) {
        try {
          navigator.sendBeacon(
            feedbackUrl,
            new Blob(
              [
                JSON.stringify({
                  decision_id: activeDecision.decision_id,
                  variant_id: activeDecision.variant_id,
                  reward: 0,
                }),
              ],
              { type: "application/json" }
            )
          );
        } catch (e) {}
      }
    });

    decide();
  }

  var roots = document.querySelectorAll("[data-cro-hero-root]");
  for (var i = 0; i < roots.length; i++) {
    initRoot(roots[i]);
  }
})();
