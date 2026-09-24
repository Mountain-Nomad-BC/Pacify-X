# Accessibility

Accessibility is part of the release contract even where no statute clearly compels a small
open-source developer tool.

**No accessibility certification or conformance claim is made.**

---

## 1. Commitments

| Area | Requirement |
|---|---|
| Keyboard operation | every interactive control is reachable and operable by keyboard |
| Screen readers | controls carry accessible labels; dynamic state changes are announced where the host supports it |
| Focus order | focus order follows the visual and logical order |
| Contrast | text and essential UI meet contrast expectations in light, dark, and high-contrast themes |
| Scalable text | layout tolerates increased text size without loss of function |
| Reduced motion | motion respects the host's reduced-motion preference |
| Status indicators | status is never conveyed by colour alone |
| Error messages | errors are announced and describe the problem in text |
| Onboarding | first-run flow is keyboard-navigable and screen-reader legible |

## 2. Theme support

The VS Code extension must work in:

- light theme;
- dark theme;
- high-contrast themes.

It must not hard-code assumptions about the host theme. PX uses the host's theme tokens rather
than fixed colours, so a user's accessibility theme applies to the PX surfaces as well.

## 3. Status without colour

PX uses textual and structural status alongside colour:

- the console shows the active model and route as text, not only as an indicator colour;
- health and degradation states are stated in words ("stale", "unavailable", "degraded") in
  addition to any visual cue;
- busy and disabled states are conveyed by attributes, not only by dimming.

## 4. Current posture and gaps

| Item | Status |
|---|---|
| Keyboard-navigable console (composer, send, stop, clear) | implemented in the Agent Console |
| Accessible labels on primary controls | implemented |
| Host theme tokens (no fixed colours) | implemented |
| Colour-independent status text | implemented |
| Screen-reader announcement of streaming updates | **partial** — streamed text is rendered progressively; announcement tuning is a **repair item** |
| Reduced-motion handling | **to verify** — a repair item |
| Automated accessibility audit in CI | **not implemented** — a repair item |
| Accessibility statement published | **this document** |
| Issue-reporting path for accessibility | email `bjc274@gmail.com` (see below) |

Reported honestly: the baseline is implemented; the audit and the announcement tuning are open
items rather than assumed-complete.

## 5. Procurement-driven requirements

For government or enterprise sales, additional requirements — Section 508, WCAG conformance
level, VPAT/ACR documentation — may become **contractual**. Those are not claimed here and would
be produced for an engagement that requires them. No VPAT is published, because publishing one
without a completed audit would be a false statement about conformance.

## 6. Reporting an accessibility problem

Email `bjc274@gmail.com` with:

- what you were trying to do;
- the assistive technology and host version;
- what happened instead.

Accessibility issues are triaged like any other defect. If an issue blocks use entirely, say so in
the subject line.