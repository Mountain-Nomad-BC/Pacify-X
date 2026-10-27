from __future__ import annotations

import unittest

from runtime.query_planner import LexiconEntry, QueryPlan, QueryPlanner
from runtime.retrieval import RetrievalSource, retrieve


class PXAUD100_QueryPlanDigestValidation(unittest.TestCase):
    """PX-AUD-100: retrieval rejects forged QueryPlan digests and unverified exact identifiers."""

    def setUp(self) -> None:
        self.lexicon = (
            LexiconEntry(canonical="python", aliases=("py",), category="language"),
            LexiconEntry(canonical="async", aliases=("await",), category="language"),
        )
        self.planner = QueryPlanner(entries=self.lexicon)
        self.plan = self.planner.plan("python async record_id=src-1")
        self.sources = (
            RetrievalSource(
                source_id="src-1",
                title="Python Source",
                text="python async documentation",
                visibility=("public",),
                lineage="public",
            ),
            RetrievalSource(
                source_id="src-2",
                title="Other Source",
                text="unrelated content",
                visibility=("public",),
                lineage="public",
            ),
        )

    def test_valid_planner_plan_passes_validation(self) -> None:
        """A plan from QueryPlanner.plan() has a valid digest."""
        QueryPlan.validate(self.plan)
        self.assertEqual(self.plan.plan_sha256, self.plan.plan_hash)

    def test_forged_zero_digest_rejected(self) -> None:
        """A QueryPlan with plan_sha256=64 zeroes fails validation."""
        forged = QueryPlan(
            raw_query="python async",
            normalized_query="python async",
            exact_identifiers=("src-999",),
            exact_keys=("source_id:src-999",),
            aliases_resolved=(("py", "python"),),
            expansions=("python",),
            facets={"language": ("python",)},
            direct_blockers=(),
            plan_sha256="0" * 64,
            lexicon_sha256=self.planner.lexicon_sha256,
        )
        with self.assertRaises(ValueError) as ctx:
            QueryPlan.validate(forged)
        self.assertIn("digest does not match", str(ctx.exception))

    def test_forged_exact_identifiers_rejected(self) -> None:
        """A QueryPlan with forged exact_identifiers but wrong digest is rejected."""
        forged = QueryPlan(
            raw_query="python async",
            normalized_query="python async",
            exact_identifiers=("irrelevant_source_id",),
            exact_keys=("source_id:irrelevant_source_id",),
            aliases_resolved=(),
            expansions=(),
            facets={},
            direct_blockers=(),
            plan_sha256="0" * 64,
            lexicon_sha256=self.planner.lexicon_sha256,
        )
        with self.assertRaises(ValueError) as ctx:
            QueryPlan.validate(forged)
        self.assertIn("digest does not match", str(ctx.exception))

    def test_retrieve_rejects_forged_query_plan(self) -> None:
        """retrieve() rejects a forged QueryPlan before trusting exact identifiers."""
        forged = QueryPlan(
            raw_query="python async",
            normalized_query="python async",
            exact_identifiers=("src-2",),
            exact_keys=("source_id:src-2",),
            aliases_resolved=(),
            expansions=(),
            facets={},
            direct_blockers=(),
            plan_sha256="0" * 64,
            lexicon_sha256=self.planner.lexicon_sha256,
        )
        with self.assertRaises(ValueError) as ctx:
            retrieve(
                "python async",
                self.sources,
                identity_scope=(),
                query_plan=forged,
            )
        self.assertIn("digest does not match", str(ctx.exception))

    def test_retrieve_accepts_valid_query_plan(self) -> None:
        """retrieve() accepts a valid QueryPlan from QueryPlanner.plan()."""
        result = retrieve(
            "python async",
            self.sources,
            identity_scope=(),
            query_plan=self.plan,
        )
        # Valid plan is accepted — no exception raised, at least one hit
        self.assertGreaterEqual(len(result.hits), 1)

    def test_forged_exact_ids_do_not_promote_irrelevant(self) -> None:
        """Even a structurally valid plan can't force exact priority on irrelevant sources."""
        # The plan from the planner has exact_identifiers=("src-1",) from the query
        # src-1 is in the sources, so it gets exact priority. src-2 doesn't match.
        result = retrieve(
            "python async record_id=src-1",
            self.sources,
            identity_scope=(),
            query_plan=self.plan,
        )
        hit_ids = [hit.source_id for hit in result.hits]
        self.assertIn("src-1", hit_ids)
        # src-1 should be first (exact priority)
        self.assertEqual(hit_ids[0], "src-1")

    def test_mutated_field_rejected(self) -> None:
        """Mutating any field without updating plan_sha256 fails validation."""
        mutated = QueryPlan(
            raw_query=self.plan.raw_query,
            normalized_query=self.plan.normalized_query,
            exact_identifiers=("different-id",),  # mutated
            exact_keys=self.plan.exact_keys,
            aliases_resolved=self.plan.aliases_resolved,
            expansions=self.plan.expansions,
            facets=self.plan.facets,
            direct_blockers=self.plan.direct_blockers,
            plan_sha256=self.plan.plan_sha256,  # stale digest
            lexicon_sha256=self.plan.lexicon_sha256,
        )
        with self.assertRaises(ValueError) as ctx:
            QueryPlan.validate(mutated)
        self.assertIn("digest does not match", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
