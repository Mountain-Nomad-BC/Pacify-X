# Boundary contract

Normalize both sides with: stable contract ID, canonical owner, method or operation, route or topic, version, field/type map, required fields, and authorization scopes.

Require evidence for:

- provider and consumer discovery;
- route/topic and version compatibility;
- required-field presence and type agreement;
- authorization denial as well as allowed access;
- event retry, duplicate suppression, and idempotency when applicable;
- migration order, compatibility window, and rollback.

Never treat generated clients, cached schemas, compiled artifacts, or documentation alone as runtime truth. A passing happy path does not prove permission or malformed-input safety.
