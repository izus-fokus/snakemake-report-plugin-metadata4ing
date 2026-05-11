from __future__ import annotations

import argparse
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TypedDict, Union

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rocrate.rocrate import ROCrate

try:
    from snakemake_report_plugin_metadata4ing.rocrate_builder import (
        M4I_HAS_KIND_OF_QUANTITY,
        WORKFLOW_RUN_CONTEXT,
        WORKFLOW_RUN_METADATA_CONFORMS_TO,
        WORKFLOW_RUN_PROFILE_CREATIVE_WORKS,
        WORKFLOW_RUN_ROOT_CONFORMS_TO,
    )
except ImportError:
    from rocrate_builder import (
        M4I_HAS_KIND_OF_QUANTITY,
        WORKFLOW_RUN_CONTEXT,
        WORKFLOW_RUN_METADATA_CONFORMS_TO,
        WORKFLOW_RUN_PROFILE_CREATIVE_WORKS,
        WORKFLOW_RUN_ROOT_CONFORMS_TO,
    )

ROCRATE_CONFORMS_TO = WORKFLOW_RUN_METADATA_CONFORMS_TO
ROOT_DATASET_CONFORMS_TO = WORKFLOW_RUN_ROOT_CONFORMS_TO
PROFILE_CREATIVE_WORKS = WORKFLOW_RUN_PROFILE_CREATIVE_WORKS

M4I = Namespace("http://w3id.org/nfdi4ing/metadata4ing#")
OBO = Namespace("http://purl.obolibrary.org/obo/")
CR = Namespace("http://mlcommons.org/croissant/")

HAS_NUMERICAL_VALUE = M4I.hasNumericalValue
HAS_STRING_VALUE = M4I.hasStringValue
HAS_UNIT = M4I.hasUnit
HAS_KIND_OF_QTY = M4I.hasKindOfQuantity
HAS_PART = OBO.BFO_0000051
HAS_INPUT = OBO.RO_0002233
HAS_OUTPUT = OBO.RO_0002234
USES_CONFIG = M4I.usesConfiguration
HAS_EMPLOYED_TOOL = M4I.hasEmployedTool
DATA_TYPE = M4I.dataType
JSON_PATH = CR.jsonPath
INVESTIGATES = M4I.investigates
EVALUATES = M4I.evaluates
USES = URIRef("https://mardi4nfdi.de/mathmoddb#uses")
DESCRIBED_BY = URIRef("https://mardi4nfdi.de/mathmoddb#describedAsDocumentedBy")
REPRESENTS = URIRef("http://semanticscience.org/resource/SIO_000210")
HAS_SOURCE = CR.source
HAS_EXTRACT = CR.extract
HAS_FILE_OBJECT = URIRef("http://mlcommons.org/croissant/FileObject")
HAS_FILE_OBJECT_ALT = URIRef("http://mlcommons.org/croissant/fileObject")

T_BENCHMARK = M4I.Benchmark
T_NUMERICAL_VARIABLE = M4I.NumericalVariable
T_PROCESSING_STEP = M4I.ProcessingStep
T_FIELD = CR.Field


@dataclass
class KGNode:
    id: str
    label: Optional[str] = None


@dataclass
class ResearchProblem(KGNode):
    pass


@dataclass
class MathematicalModel(KGNode):
    pass


@dataclass
class Publication(KGNode):
    pass


@dataclass
class NumericalVariable(KGNode):
    unit: Optional[str] = None
    quantity_kind: Optional[str] = None
    field_mapping: Optional["FieldMapping"] = None


@dataclass
class NumericalParameter(KGNode):
    numerical_value: Optional[float] = None
    unit: Optional[str] = None
    field_mapping: Optional["FieldMapping"] = None


@dataclass
class TextParameter(KGNode):
    string_value: Optional[str] = None
    unit: Optional[str] = None
    field_mapping: Optional["FieldMapping"] = None


@dataclass
class FieldMapping:
    field_id: str
    data_type: Optional[str] = None
    source_id: Optional[str] = None
    extract_id: Optional[str] = None
    json_path: Optional[str] = None
    file_object_id: Optional[str] = None
    file_object_label: Optional[str] = None


ParameterEntry = Union[NumericalParameter, TextParameter, NumericalVariable]


@dataclass
class ParameterSet(KGNode):
    identifier: Optional[str] = None
    parts: list[ParameterEntry] = field(default_factory=list)


@dataclass
class Tool(KGNode):
    pass


@dataclass
class IOObject(KGNode):
    pass


@dataclass
class ProcessingStep(KGNode):
    inputs: list[IOObject] = field(default_factory=list)
    outputs: list[IOObject] = field(default_factory=list)
    configurations: list[ParameterSet] = field(default_factory=list)
    employed_tools: list[Tool] = field(default_factory=list)


@dataclass
class SemanticBenchmark(KGNode):
    investigates: Optional[ResearchProblem] = None
    uses: Optional[MathematicalModel] = None
    evaluates: list[NumericalVariable] = field(default_factory=list)
    parameter_sets: list[ParameterSet] = field(default_factory=list)
    described_by: Optional[Publication] = None
    processing_steps: list[ProcessingStep] = field(default_factory=list)


class BenchmarkLoader:
    def __init__(self, jsonld_path: str | Path):
        self.path = Path(jsonld_path)
        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")

        self.graph = Graph()
        self.graph.parse(str(self.path), format="json-ld")
        self._field_mapping_by_variable_id = self._build_field_mapping_index()

    @staticmethod
    def _str(uri: URIRef) -> str:
        return str(uri)

    def _label(self, subject: URIRef) -> Optional[str]:
        value = self.graph.value(subject, RDFS.label)
        return str(value) if value else None

    def _scalar(self, subject: URIRef, predicate: URIRef):
        value = self.graph.value(subject, predicate)
        if value is None:
            return None
        return value.toPython() if isinstance(value, Literal) else str(value)

    def _build_field_mapping_index(self) -> dict[str, FieldMapping]:
        mapping_by_variable_id: dict[str, FieldMapping] = {}
        for field_uri in self.graph.subjects(RDF.type, T_FIELD):
            variable_uri = self.graph.value(field_uri, REPRESENTS)
            if variable_uri is None:
                continue

            source_uri = self.graph.value(field_uri, HAS_SOURCE)
            extract_uri = (
                self.graph.value(source_uri, HAS_EXTRACT) if source_uri else None
            )
            file_object_uri = None
            if source_uri:
                file_object_uri = self.graph.value(source_uri, HAS_FILE_OBJECT)
                if file_object_uri is None:
                    file_object_uri = self.graph.value(source_uri, HAS_FILE_OBJECT_ALT)

            variable_id = self._str(variable_uri)
            mapping = FieldMapping(
                field_id=self._str(field_uri),
                data_type=self._scalar(field_uri, DATA_TYPE),
                source_id=self._str(source_uri) if source_uri else None,
                extract_id=self._str(extract_uri) if extract_uri else None,
                json_path=self._scalar(extract_uri, JSON_PATH) if extract_uri else None,
                file_object_id=self._str(file_object_uri) if file_object_uri else None,
                file_object_label=(
                    self._label(file_object_uri) if file_object_uri else None
                ),
            )
            mapping_by_variable_id[variable_id] = mapping

            if "variable_" in variable_id:
                mapping_by_variable_id[
                    variable_id.replace("variable_", "metric_", 1)
                ] = mapping
            elif "metric_" in variable_id:
                mapping_by_variable_id[
                    variable_id.replace("metric_", "variable_", 1)
                ] = mapping
        return mapping_by_variable_id

    def _field_mapping(self, variable_uri: URIRef) -> Optional[FieldMapping]:
        return self._field_mapping_by_variable_id.get(self._str(variable_uri))

    def build_numerical_parameter(self, uri: URIRef) -> NumericalParameter:
        return NumericalParameter(
            id=self._str(uri),
            label=self._label(uri),
            numerical_value=self._scalar(uri, HAS_NUMERICAL_VALUE),
            unit=self._scalar(uri, HAS_UNIT),
            field_mapping=self._field_mapping(uri),
        )

    def build_text_parameter(self, uri: URIRef) -> TextParameter:
        return TextParameter(
            id=self._str(uri),
            label=self._label(uri),
            string_value=self._scalar(uri, HAS_STRING_VALUE),
            unit=self._scalar(uri, HAS_UNIT),
            field_mapping=self._field_mapping(uri),
        )

    def build_numerical_variable(self, uri: URIRef) -> NumericalVariable:
        return NumericalVariable(
            id=self._str(uri),
            label=self._label(uri),
            unit=self._scalar(uri, HAS_UNIT),
            quantity_kind=self._scalar(uri, HAS_KIND_OF_QTY),
            field_mapping=self._field_mapping(uri),
        )

    def build_parameter_entry(self, uri: URIRef) -> ParameterEntry:
        if self.graph.value(uri, HAS_STRING_VALUE):
            return self.build_text_parameter(uri)
        if (uri, RDF.type, T_NUMERICAL_VARIABLE) in self.graph:
            return self.build_numerical_variable(uri)
        return self.build_numerical_parameter(uri)

    def build_parameter_set(self, uri: URIRef) -> ParameterSet:
        return ParameterSet(
            id=self._str(uri),
            label=self._label(uri),
            identifier=self._scalar(uri, M4I.identifier),
            parts=[
                self.build_parameter_entry(part)
                for part in self.graph.objects(uri, HAS_PART)
            ],
        )

    def build_tool(self, uri: URIRef) -> Tool:
        return Tool(id=self._str(uri), label=self._label(uri))

    def build_io_object(self, uri: URIRef) -> IOObject:
        return IOObject(id=self._str(uri), label=self._label(uri))

    def build_processing_step(self, uri: URIRef) -> ProcessingStep:
        return ProcessingStep(
            id=self._str(uri),
            label=self._label(uri),
            inputs=[
                self.build_io_object(input_entity)
                for input_entity in self.graph.objects(uri, HAS_INPUT)
            ],
            outputs=[
                self.build_io_object(output_entity)
                for output_entity in self.graph.objects(uri, HAS_OUTPUT)
            ],
            configurations=[
                self.build_parameter_set(config)
                for config in self.graph.objects(uri, USES_CONFIG)
            ],
            employed_tools=[
                self.build_tool(tool)
                for tool in self.graph.objects(uri, HAS_EMPLOYED_TOOL)
            ],
        )

    def load(self) -> SemanticBenchmark:
        benchmark_uri = next(self.graph.subjects(RDF.type, T_BENCHMARK), None)
        if benchmark_uri is None:
            raise ValueError("No m4i:Benchmark node found.")

        research_problem_uri = self.graph.value(benchmark_uri, INVESTIGATES)
        model_uri = self.graph.value(benchmark_uri, USES)
        publication_uri = self.graph.value(benchmark_uri, DESCRIBED_BY)

        return SemanticBenchmark(
            id=self._str(benchmark_uri),
            label=self._label(benchmark_uri),
            investigates=(
                ResearchProblem(
                    id=self._str(research_problem_uri),
                    label=self._label(research_problem_uri),
                )
                if research_problem_uri
                else None
            ),
            uses=(
                MathematicalModel(
                    id=self._str(model_uri),
                    label=self._label(model_uri),
                )
                if model_uri
                else None
            ),
            evaluates=[
                self.build_numerical_variable(metric)
                for metric in self.graph.objects(benchmark_uri, EVALUATES)
            ],
            parameter_sets=[
                self.build_parameter_set(parameter_set)
                for parameter_set in self.graph.objects(
                    benchmark_uri, M4I.hasParameterSet
                )
            ],
            described_by=(
                Publication(
                    id=self._str(publication_uri),
                    label=self._label(publication_uri),
                )
                if publication_uri
                else None
            ),
            processing_steps=[
                self.build_processing_step(step)
                for step in self.graph.subjects(RDF.type, T_PROCESSING_STEP)
            ],
        )


class ConfigurationEntry(TypedDict):
    index: int
    config: ParameterSet
    config_id: str
    processing_step_id: str


class RunResultEntry(TypedDict):
    run_name: str
    result_ids: list[dict[str, str]]


def _iter_subfolders(input_path: Path) -> list[Path]:
    return [entry for entry in sorted(input_path.iterdir()) if entry.is_dir()]


def _collect_subcrates(subfolders: list[Path]) -> list[Path]:
    subcrates: list[Path] = []
    for subfolder in subfolders:
        subcrates.extend(sorted(subfolder.glob("SubCrate.zip")))
    return subcrates


def _add_subcrates_to_main(
    crate: ROCrate, subcrates: list[Path], input_path: Path
) -> None:
    for subcrate in subcrates:
        crate.add_file(
            source=str(subcrate),
            dest_path=str(subcrate.relative_to(input_path)),
            properties={},
        )


def _create_action_object_ids(
    input_path: Path, subfolders: list[Path]
) -> dict[str, str]:
    object_ids: dict[str, str] = {}
    for subfolder in subfolders:
        subcrate = next(iter(sorted(subfolder.glob("SubCrate.zip"))), None)
        if subcrate is None:
            continue
        object_ids[subfolder.name] = str(subcrate.relative_to(input_path))
    return object_ids


def _formal_parameter_key(part: ParameterEntry) -> tuple[Any, ...]:
    return (
        type(part).__name__,
        part.label,
        getattr(part, "unit", None),
        getattr(part, "numerical_value", None),
        getattr(part, "string_value", None),
        getattr(part, "quantity_kind", None),
    )


def _formal_parameter_payload(part_id: str, part: ParameterEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@id": part_id,
        "@type": "FormalParameter",
        "name": part.label,
    }

    unit = getattr(part, "unit", None)
    payload["additionalType"] = ""

    if unit is not None:
        payload["m4i:hasKindOfQuantity"] = {"@id": unit}

    if isinstance(part, NumericalParameter):
        payload["defaultValue"] = part.numerical_value
    elif isinstance(part, TextParameter):
        payload["defaultValue"] = part.string_value
    elif (
        isinstance(part, NumericalVariable)
        and part.quantity_kind is not None
    ):
        payload["valueReference"] = part.quantity_kind

    return payload


def _add_configuration_nodes(
    crate: ROCrate,
    benchmark_object: SemanticBenchmark,
) -> list[ConfigurationEntry]:
    if not benchmark_object.processing_steps:
        raise ValueError("Benchmark has no processing steps.")

    formal_param_registry: dict[tuple[Any, ...], str] = {}
    configuration_entries: list[ConfigurationEntry] = []

    for processing_step in benchmark_object.processing_steps:
        for index, config in enumerate(processing_step.configurations, start=1):
            config_id = f"#{uuid.uuid4()}"
            formal_parameter_ids: list[dict[str, str]] = []

            for part in config.parts:
                key = _formal_parameter_key(part)
                part_id = formal_param_registry.get(key)

                if part_id is None:
                    part_id = f"#{uuid.uuid4()}"
                    formal_param_registry[key] = part_id
                    crate.add_jsonld(_formal_parameter_payload(part_id, part))

                formal_parameter_ids.append({"@id": part_id})

            crate.add_jsonld(
                {
                    "@id": config_id,
                    "@type": "PropertyValue",
                    "name": config.label,
                    "exampleOfWork": formal_parameter_ids,
                }
            )
            configuration_entries.append(
                {
                    "index": index,
                    "config": config,
                    "config_id": config_id,
                    "processing_step_id": processing_step.id,
                }
            )

    return configuration_entries


def _normalize_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{float(value):.15g}"
    text = str(value).strip()
    if not text:
        return None
    try:
        return f"{float(text):.15g}"
    except ValueError:
        return text.lower()


def _run_parameters_file(run_folder: Path) -> Path | None:
    for candidate in ("parameter.json", "parameters.json"):
        path = run_folder / candidate
        if path.exists() and path.is_file():
            return path
    return None


def _load_run_parameters(run_folder: Path) -> dict[str, Any]:
    parameters_file = _run_parameters_file(run_folder)
    if parameters_file is None:
        return {}
    try:
        with parameters_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configuration_id_for_run(
    run_folder: Path,
    run_parameters: dict[str, Any],
    configuration_entries: list[ConfigurationEntry],
) -> str | None:
    by_identifier: dict[str, str] = {}

    for entry in configuration_entries:
        config_id = entry["config_id"]
        config = entry["config"]

        identifier_key = _normalize_value(config.identifier)
        if identifier_key:
            by_identifier[identifier_key] = config_id

    run_config_value = run_parameters.get("configuration")

    candidates = [
        _normalize_value(run_config_value),
        _normalize_value(run_folder.name),
    ]

    for candidate in candidates:
        if candidate and candidate in by_identifier:
            return by_identifier[candidate]

    return None


def _json_path_value(payload: Any, json_path: str) -> Any:
    current = payload
    for token in (part for part in json_path.strip().strip("/").split("/") if part):
        if isinstance(current, dict):
            if token not in current:
                return None
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit():
                return None
            index = int(token)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _load_json(path: Path, cache: dict[Path, Any]) -> Any:
    if path not in cache:
        with path.open("r", encoding="utf-8") as handle:
            cache[path] = json.load(handle)
    return cache[path]


def _extract_evaluated_value(
    run_folder: Path,
    metric: NumericalVariable,
    json_cache: dict[Path, Any],
) -> tuple[Any, Path | None]:
    field_mapping = metric.field_mapping
    if (
        not field_mapping
        or not field_mapping.json_path
        or not field_mapping.file_object_label
    ):
        return None, None

    source_file = run_folder / field_mapping.file_object_label
    if not source_file.exists() or not source_file.is_file():
        return None, source_file

    try:
        payload = _load_json(source_file, json_cache)
    except (OSError, json.JSONDecodeError):
        return None, source_file

    return _json_path_value(payload, field_mapping.json_path), source_file


def _add_evaluates_nodes(
    crate: ROCrate,
    benchmark_object: SemanticBenchmark,
    subfolders: list[Path],
) -> list[RunResultEntry]:
    run_results: list[RunResultEntry] = []
    if not benchmark_object.evaluates:
        return run_results

    for run_folder in subfolders:
        json_cache: dict[Path, Any] = {}
        run_metric_results: list[dict[str, str]] = []
        for metric in benchmark_object.evaluates:
            value, _ = _extract_evaluated_value(run_folder, metric, json_cache)
            if value is None:
                continue

            result_id = f"#{uuid.uuid4()}"
            node: dict[str, Any] = {
                "@id": result_id,
                "@type": "PropertyValue",
                "name": metric.label,
                "defaultValue": value,
            }
            if metric.unit:
                node["additionalType"] = metric.unit

            crate.add_jsonld(node)
            run_metric_results.append({"@id": result_id})

        run_results.append(
            {"run_name": run_folder.name, "result_ids": run_metric_results}
        )

    return run_results


def _run_results_by_name(
    run_results: list[RunResultEntry],
) -> dict[str, list[dict[str, str]]]:
    return {entry["run_name"]: entry["result_ids"] for entry in run_results}


def _configuration_entries_for_step(
    configuration_entries: list[ConfigurationEntry],
    processing_step: ProcessingStep,
) -> list[ConfigurationEntry]:
    return [
        entry
        for entry in configuration_entries
        if entry["processing_step_id"] == processing_step.id
    ]


def _add_run_actions(
    crate: ROCrate,
    subfolders: list[Path],
    object_ids_by_run: dict[str, str],
    processing_steps: list[ProcessingStep],
    configuration_entries: list[ConfigurationEntry],
    run_results_by_name: dict[str, list[dict[str, str]]],
    software_id: str,
) -> None:
    for run_folder in subfolders:
        run_name = run_folder.name
        run_object_id = object_ids_by_run.get(run_name)
        if not run_object_id:
            continue

        run_parameters = _load_run_parameters(run_folder)
        result_ids = run_results_by_name.get(run_name, [])

        for processing_step in processing_steps:
            step_configuration_entries = _configuration_entries_for_step(
                configuration_entries, processing_step
            )
            config_id = _configuration_id_for_run(
                run_folder, run_parameters, step_configuration_entries
            )

            step_name = processing_step.label or processing_step.id
            run_action: dict[str, Any] = {
                "@id": f"{uuid.uuid4()}",
                "@type": "CreateAction",
                "name": f"{step_name} {run_name}",
                "object": [{"@id": run_object_id}],
                "instrument": {"@id": software_id},
            }
            if config_id:
                run_action["object"].append({"@id": config_id})
            if result_ids:
                run_action["result"] = result_ids
            crate.add_jsonld(run_action)


def _configure_crate_metadata(crate: ROCrate, snakemake_id: str) -> None:
    crate.metadata.extra_contexts.append(WORKFLOW_RUN_CONTEXT)
    crate.metadata.extra_terms = {"m4i:hasKindOfQuantity": M4I_HAS_KIND_OF_QUANTITY}
    crate.mainEntity = {"@id": snakemake_id}
    crate.license = "https://opensource.org/licenses/MIT"
    crate.name = "NFDI4Ing Provenance"
    crate.description = "Benchmark for linear-elastic plate with a hole"
    crate.metadata["conformsTo"] = ROCRATE_CONFORMS_TO
    crate.root_dataset.append_to("conformsTo", ROOT_DATASET_CONFORMS_TO)


def _add_profile_creative_works(crate: ROCrate) -> None:
    for creative_work in PROFILE_CREATIVE_WORKS:
        crate.add_jsonld(creative_work)


def _software_application_payload(
    benchmark_object: SemanticBenchmark,
) -> tuple[str, dict[str, Any]]:
    for processing_step in benchmark_object.processing_steps:
        for tool in processing_step.employed_tools:
            software_id = tool.id or str(uuid.uuid4())
            return (
                software_id,
                {
                    "@id": software_id,
                    "@type": "SoftwareApplication",
                    "name": tool.label or software_id,
                },
            )

    software_id = str(uuid.uuid4())
    return (
        software_id,
        {
            "@id": software_id,
            "@type": "SoftwareApplication",
            "name": "Snakemake",
        },
    )


def _find_workflow_source(input_path: Path, subcrates: list[Path]) -> Path | None:
    candidates = [input_path / "Snakefile"]
    candidates.extend(subcrate.parent / "Snakefile" for subcrate in subcrates)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def create_main_ro(
    path: str | Path,
    benchmark_object: SemanticBenchmark,
    output_path: str | Path = "RO.zip",
) -> str:
    crate = ROCrate(version="1.1")
    input_path = Path(path)

    if not input_path.is_dir():
        raise NotADirectoryError(f"{path} is not a valid directory")

    subfolders = _iter_subfolders(input_path)
    subcrates = _collect_subcrates(subfolders)

    if not subcrates:
        raise ValueError(
            "No .zip files found inside subfolders of the specified directory"
        )

    _add_subcrates_to_main(crate, subcrates, input_path)

    object_ids_by_run = _create_action_object_ids(input_path, subfolders)
    configuration_entries = _add_configuration_nodes(crate, benchmark_object)
    run_results = _add_evaluates_nodes(crate, benchmark_object, subfolders)
    run_results_by_name = _run_results_by_name(run_results)

    snakemake_id = "Snakefile"
    software_id, software_payload = _software_application_payload(benchmark_object)

    _add_run_actions(
        crate=crate,
        subfolders=subfolders,
        object_ids_by_run=object_ids_by_run,
        processing_steps=benchmark_object.processing_steps,
        configuration_entries=configuration_entries,
        run_results_by_name=run_results_by_name,
        software_id=software_id,
    )
    _configure_crate_metadata(crate, snakemake_id)

    crate.add_jsonld(software_payload)
    _add_profile_creative_works(crate)

    workflow_source = _find_workflow_source(input_path, subcrates)
    if workflow_source is not None:
        crate.add_workflow(
            source=str(workflow_source),
            lang="snakemake",
            properties={"hasPart": {"@id": software_id}},
        )

    output_path = str(output_path)
    crate.write_zip(output_path)
    return output_path


def unzip_rocrate(ro_zip_path: str = "RO.zip", extract_dir: str = "RO") -> Path:
    zip_path = Path(ro_zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"RO-Crate zip not found: {zip_path}")

    output_dir = Path(extract_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create RO-Crate and run SPARQL queries on ro-crate-metadata.json"
    )
    parser.add_argument(
        "--simulation-result-path",
        help="Path containing run folders and SubCrate.zip files",
    )
    parser.add_argument("--ro-zip", default="RO.zip", help="Path to RO-Crate zip file")
    parser.add_argument(
        "--extract-dir",
        default="RO",
        help="Directory where RO.zip should be extracted",
    )
    parser.add_argument("--query", help="Single SPARQL query string to execute")
    parser.add_argument(
        "--interactive-query",
        action="store_true",
        help="Start interactive SPARQL shell",
    )
    args = parser.parse_args()

    benchmark_object = BenchmarkLoader(args.benchmark_file).load()
    create_main_ro(
        args.simulation_result_path,
        benchmark_object,
        output_path=args.ro_zip,
    )


if __name__ == "__main__":
    main()
