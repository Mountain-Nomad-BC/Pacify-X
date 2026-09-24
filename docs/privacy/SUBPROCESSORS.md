# Subprocessors

**Current status: NOT CURRENTLY APPLICABLE.**

Pacify-X operates no hosted service, so there is no subprocessor list, because there are no
subprocessors. A subprocessor is a third party engaged by *the service operator* to process data
on its behalf. There is no service operator here.

---

## Why this file exists at all

It exists as a **marked placeholder** so that when a hosted service is introduced, the subprocessor
question is answered rather than overlooked. It does not describe a current relationship, and it
must not be read as one.

## What a subprocessor list would contain (future)

If Pacify-X ever operates a hosted service processing personal data, this document would list, for
each subprocessor:

| Field | Purpose |
|---|---|
| Name | identification |
| Purpose of processing | why data is shared |
| Data categories | what is shared |
| Location / region | determines transfer analysis |
| Transfer mechanism | where outside the EEA, the safeguard relied on |
| Agreement in place | DPA status |
| Change-notification process | how customers learn of a change |

## What is true today

| Item | Value |
|---|---|
| Hosted service | none |
| Accounts | none |
| Data received by Pacify-X | none |
| Third parties engaged to process user data | none |
| Customer data shared with any third party | none |

## External providers are not subprocessors

A model provider the *user* configures and *the user* authenticates against is not a Pacify-X
subprocessor. The user is the party sending data, and the provider's terms govern it. See
[PROVIDER_DATA_HANDLING.md](../../PROVIDER_DATA_HANDLING.md).

Confusing the two would misstate the relationship in both directions: it would imply Pacify-X
controls the provider, and it would imply the user is not directly accountable for the data they
send.

## Trigger

Introducing a hosted service that processes personal data re-opens this document. It is recorded
as a reclassification trigger in `policies/release-invariants.json`.