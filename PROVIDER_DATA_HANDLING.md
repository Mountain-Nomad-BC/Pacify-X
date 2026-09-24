# Provider Data Handling

PACIFY-X routes to external model providers **only when you configure and authorise them**. Once
you do, the content you send crosses the provider boundary and **that provider's** terms govern
it.

This document explains the boundary and the per-provider facts **you** must confirm. PACIFY-X
does not assert a provider's retention or training behaviour on the provider's behalf.

---

## 1. The boundary, stated plainly

> Data you intentionally send to a provider you configured is **not** PACIFY-X-operated
> collection. It is your use of a third-party service.

The distinction matters because it determines who is accountable:

| | PACIFY-X | Provider you configured |
|---|---|---|
| Sends the request | yes, on your instruction | — |
| Receives and processes content | **no** | yes |
| Decides retention | n/a | **yes** |
| Decides training use | n/a | **yes** |
| Sets region handling | n/a | **yes** |
| Sets price | n/a | **yes** |

## 2. Defaults PACIFY-X enforces

| Control | Behaviour |
|---|---|
| Provider adapters | **denied by default** — an adapter must be admitted before use |
| Hidden cloud fallback | **prohibited** — local failure never silently grants remote permission (invariant `no-hidden-cloud-fallback`) |
| Explicit authorisation | required — unconfigured providers remain denied (invariant `explicit-provider-use-only`) |
| Credentials | stored in OS credential storage; never in the repository, config files, events, or the webview |
| Privacy-sensitive requests | may be restricted to local routing by policy |
| Denied data-collection flags | honoured where the provider exposes them (for example a zero-data-retention or data-collection-deny option) |

PACIFY-X makes the *routing* decision inspectable. It cannot make the provider's *handling*
decision for the provider.

## 3. Per-provider facts YOU must confirm

For each provider you enable, record and confirm:

| Field | Why it matters |
|---|---|
| Endpoint / base URL | Where your content actually goes |
| Is the endpoint you configured the one you intended? | Misconfiguration sends data elsewhere |
| Are prompts retained? | Determines whether your content persists after the request |
| Retention period | Determines how long |
| Is content used for training by default? | Determines whether your content can influence a model |
| Can training use be disabled? | The setting you must actually change |
| Is zero-data-retention available? | The option that limits retention |
| Region / data-residency options | Determines which jurisdiction processes the data |
| Who owns the account / API key? | Determines who is the controller |
| Where does billing data go? | Separate category from prompt content |
| Applicable acceptable-use policy | Determines permitted uses and can restrict your case |

**Do not infer any of these from PACIFY-X.** Confirm them with the provider's current
documentation, because they change.

## 4. Providers PACIFY-X can route to

PACIFY-X is model-agnostic; the set of providers available to you depends on what you configure.
Current adapter registry state is authoritative: `registry/provider_adapters.json`.

Local runtimes (a llama.cpp server on loopback, for example) are a **local** destination, not a
provider boundary. Content sent to `127.0.0.1` does not leave your machine.

## 5. What PACIFY-X does not claim

- It does **not** claim a provider has "zero retention" merely because PACIFY-X retains nothing.
- It does **not** represent a provider's training behaviour.
- It does **not** transfer the provider's obligations to the user or vice versa.
- It does **not** guarantee that a provider's behaviour today matches its behaviour tomorrow.

## 6. Cost

Any cost is between you and the provider. PACIFY-X applies the budget, allowlist, and
approval controls you configure; it never spends on your behalf without passing them.

## 7. Before you enable a provider

1. Which provider, and which endpoint exactly?
2. Does its retention/training policy accept *your* data?
3. Does its acceptable-use policy accept *your* use case?
4. Which region processes the data?
5. Are you allowed to send this data to that jurisdiction?
6. Is a zero-retention option available, and have you enabled it?

If any answer is unknown, the correct state is **provider not enabled**. Denied by default is not
a limitation — it is the safe position until you have answers.

---

See also: [DATA_FLOW.md](DATA_FLOW.md), [PRIVACY.md](PRIVACY.md),
[docs/compliance/GDPR.md](docs/compliance/GDPR.md).