"""Evidence-backed Knowledge Compiler and candidate Skill Foundry."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import keyword
import math
from pathlib import Path
import re
from typing import Iterable, Mapping

from .cognitive_core.formula_engine import Dimension, validate_dimensions
from .nsai_knowledge import (
    expected_object_relative_path,
    foundry_knowledge_payload,
    pretty_json_bytes as nsai_pretty_json_bytes,
)


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
MAX_CALCULATION_TEXT_BYTES = 4096
MAX_CALCULATION_VARIABLES = 64
CALCULATION_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
JAVASCRIPT_BINDING_RESERVED = frozenset(
    "break case catch class const continue debugger default delete do else export "
    "extends finally for function if import in instanceof new return super switch "
    "this throw try typeof var void while with yield enum implements interface let "
    "package private protected public static await null true false eval arguments".split()
)
FORMULA_ENGINE_PATH = Path(__file__).parent / "cognitive_core" / "formula_engine.py"
KNOWN_UNIT_DIMENSIONS = {
    "1": "1",
    "dimensionless": "1",
    "u": "U",
    "m": "L",
    "km": "L",
    "cm": "L",
    "mm": "L",
    "s": "T",
    "ms": "T",
    "min": "T",
    "h": "T",
    "kg": "M",
    "g": "M",
    "K": "Theta",
    "degC": "Theta",
    "delta_degC": "Theta",
}


def _unit_dimension(unit: str) -> Dimension:
    text = str(unit).strip()
    if not text:
        raise ValueError("unknown unit: empty")
    parts = re.split(r"([*/])", text)
    result = Dimension()
    operation = "*"
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if token in {"*", "/"}:
            operation = token
            continue
        name, marker, exponent_text = token.partition("^")
        if name not in KNOWN_UNIT_DIMENSIONS:
            raise ValueError(f"unknown unit: {name}")
        try:
            exponent = float(exponent_text) if marker else 1.0
        except ValueError as error:
            raise ValueError(f"invalid unit exponent: {token}") from error
        dimension = Dimension.parse(KNOWN_UNIT_DIMENSIONS[name]) ** exponent
        result = result * dimension if operation == "*" else result / dimension
    return result


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


from runtime.hash_utils import json_ascii_string_hash as _stable


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
            path.as_posix() if not path.is_absolute() else path.name,
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
    normalized_dimension: str
    formula_engine_revision: str
    edge_cases: tuple[str, ...]
    failure_cases: tuple[str, ...]


def _calculation_text(value: object, *, max_bytes: int) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > max_bytes
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise ValueError("calculation text must fit its bounded input budget")
    return value


def _calculation_identifier(value: object) -> str:
    if (
        type(value) is not str
        or CALCULATION_IDENTIFIER.fullmatch(value) is None
        or keyword.iskeyword(value)
        or value in JAVASCRIPT_BINDING_RESERVED
        or value == "pyMod"
    ):
        raise ValueError(
            "calculation identifier is invalid or reserved in a target language"
        )
    return value


def compile_calculation(spec: CalculationSpec) -> CalculationPackage:
    if type(spec) is not CalculationSpec:
        raise ValueError("calculation requires a typed specification")
    name = _calculation_identifier(
        _slug(_calculation_text(spec.name, max_bytes=256)).replace("-", "_")
    )
    equation = _calculation_text(spec.equation, max_bytes=MAX_CALCULATION_TEXT_BYTES)
    if (
        type(spec.variables) not in (tuple, list)
        or not 1 <= len(spec.variables) <= MAX_CALCULATION_VARIABLES
    ):
        raise ValueError("calculation variables require a bounded identifier list")
    variables = tuple(_calculation_identifier(value) for value in spec.variables)
    if len(set(variables)) != len(variables):
        raise ValueError("calculation variable identifiers must be unique")
    if (
        type(spec.units) is not dict
        or len(spec.units) > MAX_CALCULATION_VARIABLES + 1
        or set(spec.units) != set(variables) | {"result"}
    ):
        raise ValueError(
            "calculation requires a valid name and units for every variable plus result"
        )
    for unit in spec.units.values():
        _calculation_text(unit, max_bytes=128)
    if type(spec.dependencies) not in (tuple, list) or len(spec.dependencies) > 64:
        raise ValueError("calculation dependencies require a bounded list")
    dependencies = tuple(
        _calculation_text(value, max_bytes=256) for value in spec.dependencies
    )
    try:
        tree = ast.parse(equation, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ValueError("calculation expression syntax is invalid") from error
    _validate_calculation_tree(tree, variables)
    variable_dimensions = {
        variable: _unit_dimension(spec.units[variable]).render()
        for variable in variables
    }
    expected_dimension = _unit_dimension(spec.units["result"]).render()
    dimension_receipt = validate_dimensions(
        spec.equation, variable_dimensions, expected_dimension
    )
    arguments = ", ".join(variables)
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
        variables,
        dict(spec.units),
        dependencies,
        python_source,
        javascript_source,
        schema,
        str(dimension_receipt["output_dimension"]),
        hashlib.sha256(FORMULA_ENGINE_PATH.read_bytes()).hexdigest(),
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


def _render_candidate_bundle(
    bundle: FoundryBundle, destination: Path
) -> tuple[dict[Path, str], dict[str, object]]:
    certification = certify_foundry_bundle(bundle)
    if certification["decision"] != "certified_candidate":
        raise ValueError(
            "foundry bundle cannot be materialized before candidate certification"
        )
    root = destination.resolve() / bundle.bundle_id

    source_records = {str(row["source_id"]): row for row in bundle.sources}
    knowledge_files: list[tuple[Path, dict[str, object]]] = []
    for item in bundle.knowledge:
        payload = foundry_knowledge_payload(
            object_slug=item.object_id,
            object_type=item.kind,
            statement=item.statement,
            evidence_refs=item.evidence_refs,
            relationships=item.relationships,
            confidence=item.confidence,
            source_records=source_records,
        )
        relative = Path("knowledge") / expected_object_relative_path(payload)
        knowledge_files.append((relative, payload))

    knowledge_index_records = []
    files: dict[Path, str] = {}
    for relative, payload in sorted(
        knowledge_files, key=lambda item: str(item[1]["object_id"])
    ):
        raw = nsai_pretty_json_bytes(payload)
        files[relative] = raw.decode("utf-8")
        knowledge_index_records.append(
            {
                "object_id": payload["object_id"],
                "path": relative.relative_to("knowledge").as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": payload["status"],
                "object_type": payload["object_type"],
            }
        )

    derived_bundle = {
        "bundle_id": bundle.bundle_id,
        "state": bundle.state,
        "sources": bundle.sources,
        "knowledge": knowledge_index_records,
        "graph_edges": bundle.graph_edges,
        "skills": [skill.skill_id for skill in bundle.skills],
        "calculations": [package.calculation_id for package in bundle.calculations],
        "benchmark_count": len(bundle.benchmark_prompts),
        "fitness": bundle.fitness,
        "certification_errors": bundle.certification_errors,
        "knowledge_authority": "individual_json_objects",
    }
    files[Path("bundle.json")] = json.dumps(
        derived_bundle, indent=2, default=str, sort_keys=True
    ) + "\n"
    files[Path("certification.json")] = (
        json.dumps(certification, indent=2, sort_keys=True) + "\n"
    )
    files[Path("knowledge") / "index.json"] = (
        json.dumps(
            {
                "schema_version": "px.foundry-knowledge-index/1.0",
                "authority": "derived_navigation_only",
                "source_of_truth": "individual_object_files",
                "records": knowledge_index_records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    files[Path("graph.json")] = (
        json.dumps({"edges": bundle.graph_edges}, indent=2, sort_keys=True) + "\n"
    )
    files[Path("benchmarks.json")] = (
        json.dumps({"prompts": bundle.benchmark_prompts}, indent=2, sort_keys=True)
        + "\n"
    )
    for index, skill in enumerate(bundle.skills):
        files[Path("skills") / skill.skill_id / "SKILL.md"] = skill.skill_markdown()
        files[Path("skills") / skill.skill_id / "manifest.json"] = (
            json.dumps(asdict(skill), indent=2, sort_keys=True) + "\n"
        )
        files[Path("schemas") / f"{skill.skill_id}.schema.json"] = (
            json.dumps(bundle.schemas[index], indent=2, sort_keys=True) + "\n"
        )
    for package in bundle.calculations:
        base = Path("calculations") / package.calculation_id
        files[base / "calculation.py"] = package.python_source
        files[base / "calculation.js"] = package.javascript_source
        files[base / "input.schema.json"] = (
            json.dumps(package.input_schema, indent=2, sort_keys=True) + "\n"
        )
    files[Path("source-image.json")] = json.dumps(asdict(bundle), indent=2, sort_keys=True) + "\n"
    records = [{"path": relative.as_posix(), "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
               for relative, content in sorted(files.items(), key=lambda item: item[0].as_posix())]
    receipt = {"bundle_id": bundle.bundle_id, "state": "candidate", "files": records,
               "knowledge_object_count": len(knowledge_index_records),
               "knowledge_storage": "one_json_object_per_file", "hard_delete": False}
    return files, receipt


def _publication_identity(bundle_id, destination, project_root, project_id, run_id):
    from .archive_io import reject_path_links
    if project_root is None or type(project_id) is not str or not project_id.strip() or type(run_id) is not str or not run_id.strip():
        raise ValueError("explicit native project root, project identity and run identity required")
    if len(project_id) > 256 or len(run_id) > 256 or re.fullmatch(r"[a-f0-9]{64}", bundle_id) is None:
        raise ValueError("bounded publication identity required")
    reject_path_links(Path(project_root)); reject_path_links(Path(destination))
    project_root = Path(project_root).resolve(strict=True)
    if project_root == Path(project_root.anchor):
        raise ValueError("bounded native project root required")
    destination = Path(destination).resolve()
    directory = destination / bundle_id
    try:
        relative = directory.relative_to(project_root).as_posix()
    except ValueError:
        raise ValueError("candidate publication must remain within explicit project root") from None
    canonical = project_root / ".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates"
    if destination != canonical:
        raise ValueError("exact native knowledge-foundry candidate destination required")
    key = "foundry-publication-" + _stable({"path": relative, "bundle_id": bundle_id, "project_id": project_id, "run_id": run_id})
    return project_root, destination, directory, relative, key


def _admit_candidate_publication(root, admission_event_id, scope):
    from .operational_gap_ledger import read_snapshot, guard_work_admission
    if type(admission_event_id) is not str or not admission_event_id:
        raise ValueError("explicit current publication work admission required")
    snapshot = read_snapshot(root)
    admission = next((row for row in snapshot.get("work_admissions", []) if row.get("event_id") == admission_event_id), None)
    if admission is None:
        raise ValueError("publication admission is absent")
    effect_scope = next((row for row in admission.get("effect_scopes", []) if row.get("effect") == "write"), None)
    if effect_scope is None:
        raise ValueError("publication write admission is absent")
    scopes = effect_scope["scope"]
    guard_work_admission(snapshot, gap_id=admission["gap_id"], effect="write", scope=scopes, admission_event_id=admission_event_id)
    for target in (scope, ".agentic_engineering_os_px/runtime-core", ".agentic_engineering_os_px/resource-lifecycle"):
        if not any(target == str(x).rstrip("/") or target.startswith(str(x).rstrip("/") + "/") for x in scopes):
            raise ValueError("publication admission omits native output/custody scope")


def read_candidate_publication(bundle_id, destination, *, project_root, project_id, run_id):
    """Read only actual native committed candidate evidence; never grant activation."""
    from .archive_io import reject_path_links
    from .effect_intent import EffectIntentLedger
    from .resource_lifecycle import ResourceManager, ResourceClassification
    from .json_io import load_json_object, read_bounded_bytes
    from .studio_authority import StudioAuthorityStore
    root, destination, directory, scope, key = _publication_identity(bundle_id, destination, project_root, project_id, run_id)
    reject_path_links(directory)
    signed = load_json_object(directory / "custody.json", max_bytes=2 * 1024 * 1024)
    authority = StudioAuthorityStore.open_existing(root)
    if authority.project_identity != project_id:
        raise ValueError("publication project identity differs from native existing authority")
    body = authority.verify_receipt(signed)
    expected = {"schema_version": "px.foundry-publication-custody/1.0", "bundle_id": bundle_id,
                "project_id": project_id, "run_id": run_id, "path": scope, "authority_granted": False}
    if set(body) != set(expected) | {"resource_id", "images"} or any(body.get(k) != v for k, v in expected.items()):
        raise ValueError("candidate publication binding differs")
    fence = EffectIntentLedger(root).fence(key)
    if (fence.get("disposition") != "committed" or fence.get("result_sha256") != _stable(body)
            or fence.get("execution_id") != run_id or fence.get("effect") != "write"
            or fence.get("scopes") != [scope]):
        raise ValueError("candidate publication has no matching native commitment")
    manager = ResourceManager(root / ".agentic_engineering_os_px/runtime-core/knowledge-foundry/resources.json")
    record = next((x for x in manager.ledger.observe() if x.resource_id == body["resource_id"]), None)
    if (record is None or record.project_id != project_id or record.run_id != run_id
            or record.creator != "runtime.knowledge_foundry" or not record.retention_required
            or record.classification != ResourceClassification.EVIDENCE.value
            or record.path != str(directory.absolute()) or record.path_identity is None
            or tuple(record.path_identity) != manager._path_identity(directory)):
        raise ValueError("candidate retained resource identity differs")
    files = body.get("images")
    if type(files) is not dict or len(files) > 10000:
        raise ValueError("bounded candidate image inventory required")
    if any(type(k) is not str or type(v) is not str or re.fullmatch(r"[a-f0-9]{64}", v) is None for k,v in files.items()):
        raise ValueError("exact candidate image digests required")
    actual = set()
    for path in directory.rglob("*"):
        reject_path_links(path)
        if path.is_file(): actual.add(path.relative_to(directory).as_posix())
        if len(actual) > 10001:
            raise ValueError("candidate inventory exceeds bound")
    if actual != set(files) | {"custody.json"}:
        raise ValueError("candidate image inventory differs")
    for relative, digest in files.items():
        path = directory / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.resolve().parent != directory.resolve() and directory.resolve() not in path.resolve().parents:
            raise ValueError("candidate image path escaped")
        raw = bytes(read_bounded_bytes(path, max_bytes=16 * 1024 * 1024))
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("candidate retained image differs")
    return load_json_object(directory / "receipt.json", max_bytes=2 * 1024 * 1024)


def foundry_candidate_from_mapping(value):
    """Closed bounded JSON adapter for the existing complete candidate contract."""
    from dataclasses import fields
    from .foundry_studio_bridge import FoundryCandidateSkill, validate_foundry_candidate
    from .json_io import bounded_canonical_json_bytes
    if type(value) is not dict or set(value) != {x.name for x in fields(FoundryCandidateSkill)}:
        raise ValueError("exact full Foundry candidate fields required")
    bounded_canonical_json_bytes(value,max_bytes=256 * 1024)
    tuple_fields={"source_lineage","mechanisms","formulas","effects","tests","unknowns","contradictions"}
    if any(type(value[k]) is not list or len(value[k]) > 256 for k in tuple_fields):
        raise ValueError("bounded actual Foundry candidate arrays required")
    candidate=FoundryCandidateSkill(**{k:tuple(v) if k in tuple_fields else v for k,v in value.items()})
    validate_foundry_candidate(candidate)
    return candidate


def validate_retained_foundry_candidate(project_root, candidate, reference):
    """Actual Studio intake binding: signed bytes must reproduce the complete candidate."""
    from dataclasses import fields
    from .json_io import load_json_object, read_bounded_bytes
    from .studio_authority import StudioAuthorityStore
    from .foundry_studio_bridge import export_foundry_candidate, validate_foundry_candidate
    validate_foundry_candidate(candidate)
    if type(reference) is not dict or set(reference) != {"bundle_id", "run_id", "custody_sha256"}:
        raise ValueError("exact retained Foundry publication reference required")
    root = Path(project_root).resolve(strict=True)
    authority = StudioAuthorityStore.open_existing(root)
    destination = root / ".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates"
    read_candidate_publication(reference["bundle_id"], destination, project_root=root,
        project_id=authority.project_identity, run_id=reference["run_id"])
    directory = destination / reference["bundle_id"]
    signed = load_json_object(directory / "custody.json", max_bytes=2 * 1024 * 1024)
    body = authority.verify_receipt(signed)
    if _stable(body) != reference["custody_sha256"]:
        raise ValueError("retained Foundry custody reference differs")
    raw = bytes(read_bounded_bytes(directory / "source-image.json", max_bytes=16 * 1024 * 1024))
    if hashlib.sha256(raw).hexdigest() != body["images"]["source-image.json"]:
        raise ValueError("retained Foundry source image differs")
    image = json.loads(raw)
    if type(image) is not dict or set(image) != {x.name for x in fields(FoundryBundle)}:
        raise ValueError("exact typed Foundry source image required")
    def typed(cls, row, tuple_fields):
        if type(row) is not dict or set(row) != {x.name for x in fields(cls)}:
            raise ValueError("exact Foundry source component required")
        return cls(**{k: tuple(v) if k in tuple_fields else v for k,v in row.items()})
    bundle = FoundryBundle(image["bundle_id"], image["state"], tuple(image["sources"]),
        tuple(typed(KnowledgeObject,x,{"evidence_refs","relationships"}) for x in image["knowledge"]),
        tuple(tuple(x) for x in image["graph_edges"]),
        tuple(typed(CandidateSkill,x,{"inputs","outputs","triggers","dependencies","examples","tests","failure_cases","references"}) for x in image["skills"]),
        tuple(typed(CalculationPackage,x,{"variables","dependencies","edge_cases","failure_cases"}) for x in image["calculations"]),
        tuple(image["schemas"]), tuple(image["benchmark_prompts"]), image["fitness"], tuple(image["certification_errors"]))
    identity = _stable({"sources": bundle.sources, "knowledge": [asdict(x) for x in bundle.knowledge]})
    if bundle.bundle_id != reference["bundle_id"] or identity != bundle.bundle_id:
        raise ValueError("Foundry source image bundle identity differs")
    expected = export_foundry_candidate(bundle, candidate.skill_id)
    if _stable(asdict(expected)) != _stable(asdict(candidate)):
        raise ValueError("complete retained Foundry candidate or lineage differs")
    files, receipt = _render_candidate_bundle(bundle,destination)
    files[Path("receipt.json")] = json.dumps(receipt,indent=2,sort_keys=True)+"\n"
    if {path.as_posix():hashlib.sha256(content.encode()).hexdigest() for path,content in files.items()} != body["images"]:
        raise ValueError("retained Foundry outputs differ from typed source image")
    return expected


def materialize_candidate_bundle(bundle, destination, *, project_root=None, project_id=None, run_id=None, admission_event_id=None):
    """Publish candidate-only evidence under explicit native custody, never admission."""
    from datetime import datetime, timedelta, timezone
    import os
    from uuid import uuid4
    from .archive_io import reject_path_links
    from .effect_intent import EffectIntentLedger
    from .scope_lease import ScopeLeaseStore
    from .resource_lifecycle import ResourceManager, ResourceClassification
    from .studio_authority import StudioAuthorityStore
    from .json_io import bounded_canonical_json_bytes, read_bounded_bytes
    root, destination, directory, scope, key = _publication_identity(bundle.bundle_id, destination, project_root, project_id, run_id)
    _admit_candidate_publication(root, admission_event_id, scope)
    authority = StudioAuthorityStore.open_existing(root)
    if authority.project_identity != project_id:
        raise ValueError("publication project identity differs from native existing authority")
    files, receipt = _render_candidate_bundle(bundle, destination)
    images = {relative.as_posix(): content.encode("utf-8") for relative, content in files.items()}
    images["receipt.json"] = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    if len(images) > 10000 or sum(map(len, images.values())) > 64 * 1024 * 1024:
        raise ValueError("candidate publication exceeds bounded image inventory")
    for relative, raw in images.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in relative or ":" in relative or len(raw) > 16 * 1024 * 1024:
            raise ValueError("candidate output path or image exceeds contract")
        reject_path_links(directory / path)
    intents = EffectIntentLedger(root)
    fence = intents.fence(key)
    if fence.get("disposition") == "committed":
        previous = read_candidate_publication(bundle.bundle_id, destination, project_root=root, project_id=project_id, run_id=run_id)
        for relative, raw in images.items():
            if bytes(read_bounded_bytes(directory / relative, max_bytes=len(raw) + 1)) != raw:
                raise ValueError("candidate replay content differs")
        return previous
    if fence.get("disposition") != "new":
        raise ValueError("uncertain candidate publication requires native reconciliation")
    leases = ScopeLeaseStore(root); lease_id = "foundry-lease-" + uuid4().hex
    leases.acquire(lease_id=lease_id, execution_id=run_id, effect="write", scopes=(scope,),
                   reason="candidate evidence publication", expires_utc=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
    def require_live_owner():
        if any(row["binding"]["lease_id"]==lease_id and row["binding"]["execution_id"]==run_id for row in leases.quarantines(effect="write")):
            raise ValueError("candidate publication lease has unresolved quarantine")
        if not any(x.lease_id == lease_id and x.execution_id == run_id and x.scopes == (scope,)
                   for x in leases.active(effect="write")):
            raise ValueError("candidate publication lease expired or changed")
    primary_error = None
    try:
        require_live_owner()
        if intents.fence(key).get("disposition") != "new" or directory.exists():
            raise ValueError("candidate orphan or concurrent publication requires reconciliation")
        _admit_candidate_publication(root, admission_event_id, scope)
        intents.intend(idempotency_key=key, execution_id=run_id, effect="write", scopes=(scope,))
        directory.mkdir(parents=True, exist_ok=False); reject_path_links(directory)
        manager = ResourceManager(root / ".agentic_engineering_os_px/runtime-core/knowledge-foundry/resources.json")
        resource = manager.register_path(directory, allowed_cleanup_root=destination, project_id=project_id, run_id=run_id,
            lane_id="foundry-candidate", creator="runtime.knowledge_foundry", classification=ResourceClassification.EVIDENCE,
            retention_required=True, expected_cleanup_event="explicit_evidence_retention_review")
        body = {"schema_version": "px.foundry-publication-custody/1.0", "bundle_id": bundle.bundle_id,
                "project_id": project_id, "run_id": run_id, "path": scope, "authority_granted": False,
                "resource_id": resource.resource_id,
                "images": {k: hashlib.sha256(v).hexdigest() for k,v in images.items()}}
        signed = authority.sign_receipt(body)
        images["custody.json"] = bounded_canonical_json_bytes(signed, max_bytes=2 * 1024 * 1024)
        for relative, raw in sorted(images.items()):
            require_live_owner()
            _admit_candidate_publication(root, admission_event_id, scope)
            path = directory / relative; reject_path_links(path); path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            if bytes(read_bounded_bytes(path, max_bytes=len(raw) + 1)) != raw:
                raise ValueError("candidate publication readback differs")
        require_live_owner()
        _admit_candidate_publication(root, admission_event_id, scope)
        intents.commit(idempotency_key=key, execution_id=run_id, result_sha256=_stable(body))
        return read_candidate_publication(bundle.bundle_id, destination, project_root=root, project_id=project_id, run_id=run_id)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            leases.release(lease_id=lease_id, execution_id=run_id)
        except BaseException as release_error:
            if primary_error is None:
                raise
            BaseException.add_note(primary_error, "Foundry scope release remains uncertain: " + type(release_error).__name__)



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
