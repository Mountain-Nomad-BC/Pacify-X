"""Gremlin Nanny 2.0 — independent containment control plane for protected execution.

This package is the canonical Gremlin Nanny subsystem. It is the *external*
containment authority for protected agent/model execution: it registers the real
process identity of a protected execution, observes its effect surfaces through
isolated observers, resolves authorization, grants at most one bounded corrective
opportunity, and deterministically terminates non-compliant executions.

Hard boundaries (see GREMLIN-NANNY-PLAN.md):

* The monitored workload must never own the authority that judges or disables its
  containment. Workload code cannot forge an acknowledgment, mark itself healthy,
  rewrite policy, or remove enforcement authority.
* Containment control is isolated from workload control. The observers are
  read-only relative to the workload and are supplied by the caller, not the
  protected execution.
* Plane A (deterministic enforcement) never depends on Plane B (intelligent
  analysis) or on any LLM inference.
* Missing or failed enrollment fails closed for operations that require
  containment: a branch without proven containment stays NOT_ADMITTED.

The package exposes a single enrollment/observation facade in
:mod:`runtime.gremlin.containment`; the individual modules own the discrete
responsibilities of the plan.
"""

from __future__ import annotations

SCHEMA_VERSION = "px.gremlin-nanny/1.0"

__all__ = ["SCHEMA_VERSION"]