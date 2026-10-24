# Project revision succession authorization: issuance and verification
This contract defines the development implementation's fail-closed input format. It does not create an authorization, configure a trusted owner key, or grant production authority.

## Trust prerequisites
1. The project owner must issue a separate `px.project-revision-succession-policy/1.0` policy matching `owner-policy.schema.json`. The policy must come from a canonical governance owner and bind its exact bytes to trusted governance evidence; the repository's current release/effect-grant trust lists do not themselves establish succession authority.
2. The canonical policy verifier must verify the policy provenance against that already-established governance trust root and return literal `True`. The implementation callback is an integration seam; a lambda, caller assertion, or unsigned policy is not an acceptable production verifier.
3. The policy must identify active Ed25519 owner authorities (SSH identity, publisher, public key, fingerprint), a bounded revision scope, and revoked authorization IDs. Fingerprints are recomputed from the actual Ed25519 public-key blob.

## Authorization body and signature
The owner issues one JSON object conforming to `authorization.schema.json`, uniquely identifying successor project/campaign, exact predecessor campaign ID and raw SHA-256, exact current source digest, owner policy ID, a fresh validation policy bound to the successor campaign, the complete evidenced `intake_findings` denominator, issuer, decision, and an inclusive-start/exclusive-expiry UTC interval. The list must be derived from the successor source intake and must not be replaced by a placeholder.

`content_sha256` is SHA-256 of the unsigned fields (all fields except `signature` and `content_sha256`) serialized with PX `release_signing.canonical_bytes`. The owner signs the complete authorization JSON including `content_sha256` using OpenSSH Ed25519 namespace `pacify-x-project-revision-succession`. The detached `.sig` is supplied separately. Verification checks policy provenance, exact fields, current revocation list, scope, key/fingerprint correspondence, namespace, signature, content hash, timestamp bounds, and binding equality. Any missing input blocks activation.

## Issuance and rotation
The owner (not the implementation agent) selects the successor IDs and validation policy, confirms the predecessor and source digests, obtains/uses a dedicated owner signing key outside the repository, creates the policy and authorization artifacts, signs them, and distributes the detached signature. Rotate/revoke the authority by updating the canonical policy through its governed owner and preserve earlier policy/authorization evidence. Never put private keys in the repository.

## Activation boundaries
A valid local development admission permits local implementation and tests only. Activation additionally requires the verified owner policy, signed authorization, exact-source verifier, current write admission, and processing-order prerequisites. Non-production simulations only prepare in-memory candidates and never write active state. No current production owner policy/signature is supplied with this implementation.
