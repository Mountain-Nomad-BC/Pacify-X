# AI Limitations

PACIFY-X is software built on probabilistic models. It fails in ways that are worth knowing
before you rely on it. This list is honest rather than exhaustive.

---

## Model-level limitations

| Limitation | What it means in practice |
|---|---|
| **Hallucination** | A model can state something false with confidence — a function that does not exist, a flag that is not supported, an API that was never there. PACIFY-X's deterministic layers reduce this; they do not eliminate it. |
| **Non-deterministic generation** | The same prompt can produce different output. Do not treat generated text as reproducible unless it came from a deterministic path. |
| **Retrieval errors** | Retrieval can surface the wrong context, or miss the right context. A confidently-answered question built on a retrieval miss is still wrong. |
| **Stale knowledge** | Indexes, graphs, and memory reflect the moment they were built. After the source changes they can be wrong until reconciled. |
| **Provider drift** | An external provider can change a model's behaviour, availability, or pricing, or retire a model, without notice to you. |
| **Model replacement** | A model you pinned may become unavailable. A replacement is a different system with different behaviour, even at the same name. |
| **Context limits** | Long inputs are truncated or summarised. Something you said may not have reached the model. |

## Interaction-level limitations

| Limitation | What it means in practice |
|---|---|
| **Prompt injection** | Content the model reads — a file, a web page, a document — can contain instructions that attempt to redirect it. PACIFY-X separates retrieved text from system authority, but this is an active, unsolved class of problem. |
| **Data poisoning** | Content ingested into knowledge or memory can be wrong or adversarial. Candidate admission is gated; the gate is not a proof of truth. |
| **Insecure generated code** | Generated code can be insecure, incorrect, or subtly wrong in ways that pass a casual reading. |
| **Unsafe command suggestions** | A model can suggest a destructive command. Suggestions are not executions — but a human can approve one. Read before you approve. |
| **Confident wrongness in explanations** | A clear explanation is not evidence of a correct one. |

## Verification limits

| Limitation | What it means in practice |
|---|---|
| **Automated verification is bounded** | Tests confirm what they test. Passing tests do not prove the absence of defects. |
| **Certification is scoped** | A passing certification proves the exact frozen artifact met the exact validation profile. It is not a warranty and not a penetration test. |
| **Self-certification** | PACIFY-X certification is self-certification against its own included profile. It is not an independent assessment. |
| **Evidence is only as good as its binding** | Evidence is meaningful when it binds to exact artifact bytes. Unbound claims are weaker than they look. |

## What PACIFY-X does about it

PACIFY-X mitigates these rather than pretending they do not exist:

- deterministic resolution before model inference, so the model is not asked to rediscover known
  facts;
- source-attributed retrieval, so claims can be traced;
- capability and action registries, so the model selects from a known set instead of inventing
  commands;
- authority and approval gates, so a model's opinion cannot become an effect;
- receipts and evidence, so an outcome is reviewable;
- honest degradation, so a stale index or an unavailable runtime is *reported*, not papered over.

## The operating assumption

Treat every AI output as a **proposal** until it is verified against something other than the AI.
That is the assumption PACIFY-X itself is built on, and it is the assumption you should use when
you run it.

---

See also: [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md), [DISCLAIMER.md](DISCLAIMER.md),
[HIGH_RISK_AND_CONSEQUENTIAL_USE.md](HIGH_RISK_AND_CONSEQUENTIAL_USE.md).