---
name: validate-physical-media-deliverables
description: Validate CAD, manufacturing, robotics, and media deliverables against explicit technical promises and independent checks. Use when generated geometry, robot descriptions, fabrication artifacts, images, audio, or video must be proven complete rather than merely produced.
---

# Validate Physical and Media Deliverables

1. Establish one reviewable source artifact and a declared chain of generated derivatives, providers, edits, and final deliverables.
2. Compare every promised format, dimension, duration, codec, frame count, channel, or companion artifact with observed evidence. Missing observations remain unknown.
3. Reject silent provider or quality downgrades. Version the provider support envelope and health check the requested mode before generation.
4. For CAD, validate dimensions, clearances, topology, manifoldness, interference, stable semantic geometry references, and deterministic format generation.
5. For manufacturing, add material- and process-specific preflight with blockers, warnings, and unknowns. A rendered mesh or image is not proof of manufacturability.
6. For robotics, validate links, frames, joints, inertials, limits, sensors, collision geometry, and planning semantics. Generated URDF, SDF, or SRDF is not proof of safe motion.
7. For media, preserve the artifact chain and verify the delivered technical properties independently of provider success messages.
8. Keep automatic remediation constrained by scope, cost, authority, risk, dependencies, and revalidation.

Use `runtime.completion_controls.validate_delivery`. Completion remains blocked on mismatches, missing independent checks, unknown required properties, or provider downgrade.
