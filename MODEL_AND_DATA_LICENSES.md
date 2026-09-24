# Model and Data Licenses

PACIFY-X does **not** bundle model weights. It is model-agnostic: it discovers, admits, and
operates models you supply, and it can recommend models and explain where to obtain them.

This means model licensing is a **registry**, not a single statement — and it is yours to
confirm for the models you actually use.

**The Apache-2.0 licence of PACIFY-X does not cover, extend to, or grant any rights in
third-party model weights or datasets.**

---

## 1. How PACIFY-X handles models

| Behaviour | Status |
|---|---|
| Ship model weights | **no** |
| Auto-download model weights | **no** — prohibited unless an explicitly approval-gated step is added later |
| Discover models already present | yes |
| Recommend models | yes |
| Explain how to obtain them | yes |
| Prepare an installation plan | yes |
| Record identity, source, license, revision, size, hash | yes, when a model is admitted |

The governing policy is `models/external-runtime-policy.json`
(`normal_requests_may_download: false`), enforced by release invariant
`no-unapproved-model-download`.

## 2. What must be recorded for every admitted model

When an operator admits a model, PACIFY-X records:

| Field | Purpose |
|---|---|
| model name / ID | identity |
| source repository | provenance |
| immutable revision | reproducibility |
| exact filename | reproducibility |
| quantization | behaviour and size |
| expected size | disk disclosure |
| SHA-256 of the artifact | **the identity is the hash, never the filename** |
| licence | legal |
| allowed commercial use | legal |
| redistribution permitted? | legal |
| derivatives / fine-tuning restrictions | legal |
| attribution required? | legal |
| acceptable-use restrictions | legal |
| destination path | custody |

A model with an unknown licence is **not admitted**. "Available on GitHub" is not equivalent to
"licensed for your use."

## 3. Licence registry

Because PACIFY-X ships no weights, this registry documents the **model families the project
recommends or tests with** and the licence facts an operator must confirm. Verify each against
the upstream source before use — licences change.

| Model family | Typical source | Operator must confirm |
|---|---|---|
| Qwen2.5 / Qwen3 / Qwen3.5 (various sizes, MoE variants) | Alibaba / upstream HF repo | exact licence per size and revision; acceptable-use policy; commercial-use terms |
| Any GGUF conversion of the above | the specific converter's repo | that the conversion is licensed and that the conversion's licence matches the base model's |
| Any other model the operator supplies | as supplied | every field in §2 |

**PACIFY-X does not assert a model's licence.** The `license` field in a model record is a
*recorded fact about the source*, not a PACIFY-X warranty, and it must be verified at the source.

## 4. Dataset licences

PACIFY-X does not redistribute training datasets. If you ingest external content into knowledge
(§5), the dataset's licence governs that content.

## 5. Ingested content and provenance

Any external content that enters persistent or canonical knowledge must carry provenance:

| Field | Purpose |
|---|---|
| source URL / repository | traceability |
| commit / revision / date | reproducibility |
| licence | legal |
| author / owner | attribution |
| may it be redistributed? | legal |
| is it quoted, transformed, summarised, or only indexed? | determines the rights needed |
| hash | integrity |
| removal / takedown path | responsiveness |

**Rules:**

- Do not copy large copyrighted bodies into a shared or public knowledge pack without rights.
- Do not strip required attribution.
- Do not publish private-repository content into public knowledge.
- A private-to-public knowledge promotion passes a **declassification gate**; it is not a side
  effect of ingestion.

## 6. The boundary worth repeating

> Licensing questions attach to the artifacts **you** obtain and the content **you** ingest.
> PACIFY-X provides the machinery to record and honour those facts. It does not absorb your
> licensing obligations.

## 7. Verifying this in the tree

```powershell
# models the project references
python -c "import json;d=json.load(open('models/model-portfolio.json'));[print(m['model_id'], m.get('artifact_sha256'), m.get('source_repo')) for m in d['models']]"

# the no-auto-download policy
python -c "import json;print(json.load(open('models/external-runtime-policy.json'))['authority'])"
```

## 8. Reporting a licensing concern

If you believe content in this repository is incorrectly licensed, or requires attribution not
present, contact `bjc274@gmail.com`.