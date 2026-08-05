"""Evidence-backed Knowledge Compiler and candidate Skill Foundry."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable, Mapping


WORD = re.compile(r"[a-z0-9]+")
WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")
HEADING = re.compile(r"^#{1,6}\s+(.+)$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)(.+)$")
CAPABILITY_TERMS = {
    "reasoning": ("reason", "infer", "decision"),
    "memory": ("memory", "remember", "knowledge"),
    "planning": ("plan", "workflow", "procedure"),
    "calculation": ("calculate", "calculation", "equation", "formula", "units"),
    "validator": ("validate", "verify", "certify", "test"),
    "correction": ("correct", "repair", "self-heal", "supersede"),
    "engineering": ("engineer", "implementation", "code"),
    "retriever": ("retrieve", "search", "rerank"),
    "generator": ("generate", "produce", "emit", "build"),
}
ALLOWED_AST = {
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
}
MAX_CALCULATION_AST_NODES = 64
MAX_CALCULATION_DEPTH = 16
MAX_CALCULATION_MAGNITUDE = 1e100
MAX_CALCULATION_EXPONENT = 16


def _expression_depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return (
        1 if not children else 1 + max(_expression_depth(child) for child in children)
    )


def _validate_calculation_tree(tree: ast.Expression, variables: Iterable[str]) -> None:
    declared = set(variables)
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_CALCULATION_AST_NODES:
        raise ValueError("calculation exceeds the AST node limit")
    if _expression_depth(tree) > MAX_CALCULATION_DEPTH:
        raise ValueError("calculation exceeds the expression depth limit")
    for node in nodes:
        if type(node) not in ALLOWED_AST:
            raise ValueError(f"unsupported calculation syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in declared:
            raise ValueError(f"undeclared calculation variable: {node.id}")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(
                    "calculation constants must be numeric and cannot be booleans"
                )
            if (
                not math.isfinite(float(node.value))
                or abs(float(node.value)) > MAX_CALCULATION_MAGNITUDE
            ):
                raise ValueError(
                    "calculation constant is non-finite or exceeds the magnitude limit"
                )


def _render_javascript(node: ast.AST) -> str:
    if isinstance(node, ast.Expression):
        return _render_javascript(node.body)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.UnaryOp):
        symbol = "-" if isinstance(node.op, ast.USub) else "+"
        return f"({symbol}{_render_javascript(node.operand)})"
    if isinstance(node, ast.BinOp):
        left, right = _render_javascript(node.left), _render_javascript(node.right)
        if isinstance(node.op, ast.Mod):
            return f"pyMod({left}, {right})"
        symbols = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Pow: "**",
        }
        return f"({left} {symbols[type(node.op)]} {right})"
    raise ValueError(f"unsupported calculation syntax: {type(node).__name__}")


def _interpret_calculation(node: ast.AST, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _interpret_calculation(node.body, values)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        value = _interpret_calculation(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if not isinstance(node, ast.BinOp):
        raise ValueError(f"unsupported calculation syntax: {type(node).__name__}")
    left = _interpret_calculation(node.left, values)
    right = _interpret_calculation(node.right, values)
    try:
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        elif isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            result = left / right
        elif isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("modulo by zero")
            result = left % right
        elif isinstance(node.op, ast.Pow):
            if abs(right) > MAX_CALCULATION_EXPONENT:
                raise ValueError("calculation exponent exceeds the bound")
            if left == 0 and right < 0:
                raise ValueError("zero cannot be raised to a negative exponent")
            result = left**right
            if isinstance(result, complex):
                raise ValueError("complex calculation results are forbidden")
        else:
            raise ValueError(
                f"unsupported calculation operator: {type(node.op).__name__}"
            )
    except OverflowError as error:
        raise ValueError("calculation overflow") from error
    if (
        not math.isfinite(float(result))
        or abs(float(result)) > MAX_CALCULATION_MAGNITUDE
    ):
        raise ValueError(
            "calculation result is non-finite or exceeds the magnitude limit"
        )
    return float(result)


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _slug(value: str) -> str:
    return "-".join(WORD.findall(value.casefold()))[:63].strip("-") or "candidate-skill"


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    source_id: str
    source_kind: str
    locator: str
    sha256: str
    text: str
    license: str
    citation: str | None = None
    version: str | None = None

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        source_kind: str = "engineering_note",
        license: str = "internal-reference",
        citation: str | None = None,
        version: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> "SourceArtifact":
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ValueError("source exceeds the bounded foundry input size")
        text = data.decode("utf-8")
        return cls(
            _slug(path.stem),
            source_kind,
            path.as_posix(),
            hashlib.sha256(data).hexdigest(),
            text,
            license,
            citation,
            version,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeObject:
    object_id: str
    kind: str
    statement: str
    evidence_refs: tuple[str, ...]
    relationships: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class CandidateSkill:
    skill_id: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    triggers: tuple[str, ...]
    dependencies: tuple[str, ...]
    examples: tuple[str, ...]
    tests: tuple[str, ...]
    failure_cases: tuple[str, ...]
    confidence: float
    references: tuple[str, ...]
    status: str = "candidate"

    def skill_markdown(self) -> str:
        description = (
            f"{self.purpose} Use when a task requires {', '.join(self.triggers)}; "
            "keep outputs candidate-only until tests and admission evidence pass."
        )
        procedure = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(
                (
                    "Resolve and hash every source reference.",
                    "Load only the source fragments required for this task.",
                    "Produce the declared outputs with evidence links.",
                    "Run positive, negative, and failure-boundary tests.",
                    "Return a candidate artifact; request separate admission before activation.",
                ),
                1,
            )
        )
        return (
            f"---\nname: {self.skill_id}\ndescription: {json.dumps(description)}\n---\n\n"
            f"# {self.skill_id}\n\n{self.purpose}\n\n## Procedure\n\n{procedure}\n\n"
            f"## Failure boundaries\n\n"
            + "\n".join(f"- {item}" for item in self.failure_cases)
            + "\n"
        )


@dataclass(frozen=True, slots=True)
class CalculationSpec:
    name: str
    equation: str
    variables: tuple[str, ...]
    units: Mapping[str, str]
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalculationPackage:
    calculation_id: str
    equation: str
    variables: tuple[str, ...]
    units: Mapping[str, str]
    dependencies: tuple[str, ...]
    python_source: str
    javascript_source: str
    input_schema: Mapping[str, object]
    edge_cases: tuple[str, ...]
    failure_cases: tuple[str, ...]


def compile_calculation(spec: CalculationSpec) -> CalculationPackage:
    name = _slug(spec.name).replace("-", "_")
    if (
        not name.isidentifier()
        or not spec.variables
        or set(spec.units) != set(spec.variables) | {"result"}
    ):
        raise ValueError(
            "calculation requires a valid name and units for every variable plus result"
        )
    tree = ast.parse(spec.equation, mode="eval")
    _validate_calculation_tree(tree, spec.variables)
    arguments = ", ".join(spec.variables)
    python_source = f"def {name}({arguments}):\n    return {spec.equation}\n"
    javascript_expression = _render_javascript(tree)
    javascript_helper = (
        "const pyMod = (a, b) => ((a % b) + b) % b;\n"
        if any(isinstance(node, ast.Mod) for node in ast.walk(tree))
        else ""
    )
    javascript_source = f"{javascript_helper}export function {name}({arguments}) {{\n  return {javascript_expression};\n}}\n"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(spec.variables),
        "additionalProperties": False,
        "properties": {
            variable: {"type": "number", "x-unit": spec.units[variable]}
            for variable in spec.variables
        },
    }
    return CalculationPackage(
        name,
        spec.equation,
        spec.variables,
        dict(spec.units),
        spec.dependencies,
        python_source,
        javascript_source,
        schema,
        (
            "zero",
            "negative input where domain permits",
            "large finite values",
            "boundary units",
        ),
        ("division by zero", "non-numeric input", "unit mismatch", "non-finite result"),
    )


def evaluate_calculation(
    package: CalculationPackage, values: Mapping[str, float]
) -> float:
    if set(values) != set(package.variables):
        raise ValueError("calculation inputs do not match the variable contract")
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"calculation input {name} must be numeric and cannot be boolean"
            )
        if (
            not math.isfinite(float(value))
            or abs(float(value)) > MAX_CALCULATION_MAGNITUDE
        ):
            raise ValueError(
                f"calculation input {name} is non-finite or exceeds the magnitude limit"
            )
    tree = ast.parse(package.equation, mode="eval")
    _validate_calculation_tree(tree, package.variables)
    return _interpret_calculation(tree, values)


@dataclass(frozen=True, slots=True)
class FoundryBundle:
    bundle_id: str
    state: str
    sources: tuple[Mapping[str, object], ...]
    knowledge: tuple[KnowledgeObject, ...]
    graph_edges: tuple[tuple[str, str], ...]
    skills: tuple[CandidateSkill, ...]
    calculations: tuple[CalculationPackage, ...]
    schemas: tuple[Mapping[str, object], ...]
    benchmark_prompts: tuple[str, ...]
    fitness: Mapping[str, float]
    certification_errors: tuple[str, ...]


def compile_foundry_bundle(
    sources: Iterable[SourceArtifact],
    *,
    calculations: Iterable[CalculationSpec] = (),
    registry_capability_ids: Iterable[str] = (),
) -> FoundryBundle:
    values = tuple(sources)
    if not values:
        raise ValueError("foundry requires at least one source")
    ids = [source.source_id for source in values]
    if len(ids) != len(set(ids)):
        raise ValueError("source IDs must be unique")
    errors = []
    objects: dict[str, KnowledgeObject] = {}
    graph_edges = set()
    aggregate = []
    for source in values:
        actual = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
        if actual != source.sha256:
            errors.append(f"source_hash_mismatch:{source.source_id}")
        if not source.license:
            errors.append(f"source_license_missing:{source.source_id}")
        if (
            source.source_kind in {"paper", "standard", "white_paper"}
            and not source.citation
        ):
            errors.append(f"research_citation_missing:{source.source_id}")
        relationships = tuple(sorted(set(WIKI_LINK.findall(source.text))))
        for relation in relationships:
            graph_edges.add((source.source_id, _slug(relation)))
        for line in source.text.splitlines():
            cleaned = " ".join(line.strip().split())
            if not cleaned:
                continue
            heading = HEADING.match(cleaned)
            listed = LIST_ITEM.match(cleaned)
            statement = (
                heading.group(1) if heading else listed.group(1) if listed else cleaned
            )
            if len(statement) < 8:
                continue
            kind = "procedure" if listed else "concept" if heading else "claim"
            normalized = statement.casefold()
            object_id = f"kn-{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"
            if object_id in objects:
                prior = objects[object_id]
                objects[object_id] = KnowledgeObject(
                    object_id,
                    prior.kind,
                    prior.statement,
                    tuple(sorted(set((*prior.evidence_refs, source.source_id)))),
                    tuple(sorted(set((*prior.relationships, *relationships)))),
                    min(1.0, prior.confidence + 0.1),
                )
            else:
                objects[object_id] = KnowledgeObject(
                    object_id, kind, statement, (source.source_id,), relationships, 0.6
                )
            aggregate.append(statement)
    text = " ".join(aggregate).casefold()
    existing = set(map(str, registry_capability_ids))
    skills = []
    for capability, terms in CAPABILITY_TERMS.items():
        hits = tuple(term for term in terms if term in text)
        if not hits:
            continue
        skill_id = _slug(f"{capability}-from-knowledge")
        if skill_id in existing:
            errors.append(f"duplicate_capability:{skill_id}")
            continue
        references = tuple(source.source_id for source in values)
        skills.append(
            CandidateSkill(
                skill_id,
                f"Apply evidence-backed {capability} extracted from the supplied canonical knowledge.",
                ("task", "evidence_refs"),
                (f"{capability}_result", "evidence_receipt"),
                hits,
                (),
                (f"Use the compiled {capability} procedure on a bounded example.",),
                (
                    "positive_case",
                    "negative_case",
                    "missing_evidence",
                    "effect_boundary",
                ),
                (
                    "source evidence is missing",
                    "input falls outside source assumptions",
                    "tests do not reproduce",
                ),
                min(0.95, 0.55 + 0.05 * len(hits)),
                references,
            )
        )
    compiled_calculations = tuple(compile_calculation(spec) for spec in calculations)
    schemas = tuple(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": skill.skill_id,
            "type": "object",
            "required": list(skill.inputs),
            "properties": {name: {} for name in skill.inputs},
            "additionalProperties": False,
        }
        for skill in skills
    ) + tuple(package.input_schema for package in compiled_calculations)
    benchmarks = tuple(
        f"Given only evidence {', '.join(skill.references)}, exercise {skill.skill_id} and cite every supported output."
        for skill in skills
    )
    knowledge = tuple(objects[key] for key in sorted(objects))
    evidence_coverage = sum(bool(item.evidence_refs) for item in knowledge) / max(
        1, len(knowledge)
    )
    fitness = {
        "evidence_coverage": round(evidence_coverage, 6),
        "source_count": float(len(values)),
        "knowledge_object_count": float(len(knowledge)),
        "skill_candidate_count": float(len(skills)),
        "calculation_count": float(len(compiled_calculations)),
        "duplicate_ratio": round(1 - len(knowledge) / max(1, len(aggregate)), 6),
    }
    source_records = tuple(
        {
            "source_id": source.source_id,
            "source_kind": source.source_kind,
            "locator": source.locator,
            "sha256": source.sha256,
            "license": source.license,
            "citation": source.citation,
            "version": source.version,
        }
        for source in values
    )
    bundle_id = _stable(
        {"sources": source_records, "knowledge": [asdict(item) for item in knowledge]}
    )
    return FoundryBundle(
        bundle_id,
        "candidate",
        source_records,
        knowledge,
        tuple(sorted(graph_edges)),
        tuple(skills),
        compiled_calculations,
        schemas,
        benchmarks,
        fitness,
        tuple(sorted(set(errors))),
    )


def certify_foundry_bundle(bundle: FoundryBundle) -> dict[str, object]:
    errors = list(bundle.certification_errors)
    if not bundle.knowledge:
        errors.append("canonical_knowledge_empty")
    for skill in bundle.skills:
        if skill.status != "candidate" or not all(
            (
                skill.inputs,
                skill.outputs,
                skill.triggers,
                skill.tests,
                skill.failure_cases,
                skill.references,
            )
        ):
            errors.append(f"skill_contract_incomplete:{skill.skill_id}")
        if not skill.skill_markdown().startswith("---\n"):
            errors.append(f"skill_render_invalid:{skill.skill_id}")
    for package in bundle.calculations:
        try:
            ast.parse(package.python_source)
        except SyntaxError:
            errors.append(f"calculation_python_invalid:{package.calculation_id}")
    return {
        "bundle_id": bundle.bundle_id,
        "decision": "certified_candidate" if not errors else "not_certified",
        "errors": tuple(sorted(set(errors))),
        "activation": "candidate_only",
        "auto_activate": False,
        "checked": {
            "sources": len(bundle.sources),
            "knowledge": len(bundle.knowledge),
            "skills": len(bundle.skills),
            "calculations": len(bundle.calculations),
            "schemas": len(bundle.schemas),
            "benchmarks": len(bundle.benchmark_prompts),
        },
    }


def materialize_candidate_bundle(
    bundle: FoundryBundle, destination: Path
) -> dict[str, object]:
    certification = certify_foundry_bundle(bundle)
    if certification["decision"] != "certified_candidate":
        raise ValueError(
            "foundry bundle cannot be materialized before candidate certification"
        )
    root = destination.resolve() / bundle.bundle_id
    root.mkdir(parents=True, exist_ok=False)
    files = {}
    files[Path("bundle.json")] = (
        json.dumps(asdict(bundle), indent=2, default=str) + "\n"
    )
    files[Path("certification.json")] = json.dumps(certification, indent=2) + "\n"
    files[Path("knowledge.json")] = (
        json.dumps([asdict(item) for item in bundle.knowledge], indent=2) + "\n"
    )
    files[Path("graph.json")] = (
        json.dumps({"edges": bundle.graph_edges}, indent=2) + "\n"
    )
    files[Path("benchmarks.json")] = (
        json.dumps({"prompts": bundle.benchmark_prompts}, indent=2) + "\n"
    )
    for index, skill in enumerate(bundle.skills):
        files[Path("skills") / skill.skill_id / "SKILL.md"] = skill.skill_markdown()
        files[Path("skills") / skill.skill_id / "manifest.json"] = (
            json.dumps(asdict(skill), indent=2) + "\n"
        )
        files[Path("schemas") / f"{skill.skill_id}.schema.json"] = (
            json.dumps(bundle.schemas[index], indent=2) + "\n"
        )
    for package in bundle.calculations:
        base = Path("calculations") / package.calculation_id
        files[base / "calculation.py"] = package.python_source
        files[base / "calculation.js"] = package.javascript_source
        files[base / "input.schema.json"] = (
            json.dumps(package.input_schema, indent=2) + "\n"
        )
    records = []
    for relative, content in sorted(files.items(), key=lambda item: item[0].as_posix()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        records.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    receipt = {
        "bundle_id": bundle.bundle_id,
        "state": "candidate",
        "files": records,
        "hard_delete": False,
    }
    with (root / "receipt.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    return receipt


def compose_candidate_skills(
    skills: Iterable[CandidateSkill], *, name: str
) -> CandidateSkill:
    values = tuple(skills)
    if len(values) < 2 or any(skill.status != "candidate" for skill in values):
        raise ValueError("composition requires at least two candidate skills")
    return CandidateSkill(
        _slug(name),
        f"Compose {', '.join(skill.skill_id for skill in values)} without duplicating their source knowledge.",
        tuple(sorted({item for skill in values for item in skill.inputs})),
        tuple(sorted({item for skill in values for item in skill.outputs})),
        tuple(sorted({item for skill in values for item in skill.triggers})),
        tuple(sorted(skill.skill_id for skill in values)),
        tuple(item for skill in values for item in skill.examples),
        (
            "composition_happy_path",
            "dependency_failure",
            "conflicting_output",
            "evidence_lineage",
        ),
        (
            "dependency is not admitted",
            "outputs conflict",
            "combined effects exceed policy",
        ),
        min(skill.confidence for skill in values),
        tuple(sorted({item for skill in values for item in skill.references})),
    )


def evolution_recommendations(
    skills: Iterable[CandidateSkill],
    *,
    usage: Mapping[str, int],
    failure_rates: Mapping[str, float],
) -> tuple[Mapping[str, object], ...]:
    values = tuple(skills)
    recommendations = []
    for skill in values:
        if usage.get(skill.skill_id, 0) == 0:
            recommendations.append(
                {
                    "skill_id": skill.skill_id,
                    "action": "review_for_deprecation",
                    "automatic": False,
                }
            )
        if failure_rates.get(skill.skill_id, 0.0) > 0.2:
            recommendations.append(
                {
                    "skill_id": skill.skill_id,
                    "action": "repair_and_recertify",
                    "automatic": False,
                }
            )
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            overlap = set(left.outputs) & set(right.outputs)
            if overlap:
                recommendations.append(
                    {
                        "skills": (left.skill_id, right.skill_id),
                        "action": "review_merge_or_boundary",
                        "overlap": tuple(sorted(overlap)),
                        "automatic": False,
                    }
                )
    return tuple(recommendations)
