---
name: govern-visual-runtime-accessibility
description: Audit or implement WebGL, canvas, SVG, animation, and embedded visual surfaces so motion preferences, GPU/memory budgets, keyboard access, state freshness, and cross-frame settings are enforced. Use for Three.js, graph renderers, animation loops, export buffers, or iframe-hosted visualizations.
---

# Govern Visual Runtime Accessibility

1. Resolve effective motion and visual-quality settings from user preference, operating-system preference, and application policy.
2. Render once when motion is reduced; start continuous frame loops only when permitted and cancel them on teardown or invisibility.
3. Preserve drawing buffers only for an explicit export window or measured requirement.
4. Bound pixel ratio, geometry, texture, and frame work to the active resource tier.
5. Propagate allowed visual settings across frame boundaries using a versioned, origin-checked contract.
6. Give graph nodes keyboard focus, activation semantics, labels, and a non-visual equivalent.
7. Clear stale selection/focus when underlying data changes.
8. Verify reduced-motion, keyboard-only, high-contrast, resize, teardown, and embedded-frame behavior.
