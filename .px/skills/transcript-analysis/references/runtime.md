# Transcript runtime

Use `engineering-bootstrap transcripts profile` to inspect resolved configuration. No workstation path is a committed default. An external adapter root may be supplied through an explicit profile stored in the active project or outside the repository.

Use `transcripts adapter-plan` to produce a contained argv plan for an external runner. The plan records the runner hash, disables shell interpretation, and grants no execution authority.

Use `transcripts ingest` without `--apply` first. Applied targeted runs are created under `<output-root>/<queue-id>/runs/<run-id>` and never update a `latest` pointer.

Queue adapters write canonical JSONL records satisfying `contracts/transcripts/transcript-record.schema.json`. Import them with `transcripts records`, validate the entire run with `transcripts validate`, then use `transcripts export` for selected conversations.

Prompt text and profile commands do not grant execution. An external queue runner requires the normal tool authorization boundary.
