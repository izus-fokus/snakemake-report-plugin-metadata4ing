from __future__ import annotations

import argparse
import json
import uuid
import zipfile
from importlib import resources
from pathlib import Path
from typing import Any, TypedDict

from rdflib import Graph
from rocrate.rocrate import ROCrate

try:
    from snakemake_report_plugin_metadata4ing.models import ProvenanceResult
    from snakemake_report_plugin_metadata4ing.utils import get_mime_type
    from . import semantic_benchmark
except ImportError:
    from models import ProvenanceResult
    from utils import get_mime_type

    import semantic_benchmark

DEFAULT_BENCHMARK_FILE = (
    "/Users/mahdi/Documents/GitHub/NFDI4IngModelValidationPlatform/examples/"
    "linear-elastic-plate-with-hole/benchmark.json"
)
DEFAULT_SIMULATION_RESULT_PATH = (
    "/Users/mahdi/Documents/GitHub/NFDI4IngModelValidationPlatform/examples/"
    "linear-elastic-plate-with-hole/fenics/results"
)
M4I_HAS_KIND_OF_QUANTITY = "http://w3id.org/nfdi4ing/metadata4ing#hasKindOfQuantity"
ROCRATE_CONFORMS_TO = [
    {"@id": "https://w3id.org/ro/crate/1.1"},
    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
]
ROOT_DATASET_CONFORMS_TO = [
    {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
    {"@id": "https://w3id.org/ro/wfrun/workflow/0.5"},
    {"@id": "https://w3id.org/ro/wfrun/provenance/0.5"},
    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
]
PROFILE_CREATIVE_WORKS = (
    {
        "@id": "https://w3id.org/ro/wfrun/process/0.5",
        "@type": "CreativeWork",
        "name": "Process Run Crate",
        "version": "0.5",
    },
    {
        "@id": "https://w3id.org/ro/wfrun/workflow/0.5",
        "@type": "CreativeWork",
        "name": "Workflow Run Crate",
        "version": "0.5",
    },
    {
        "@id": "https://w3id.org/ro/wfrun/provenance/0.5",
        "@type": "CreativeWork",
        "name": "Provenance Run Crate",
        "version": "0.5",
    },
    {
        "@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0",
        "@type": "CreativeWork",
        "name": "Workflow RO-Crate",
        "version": "1.0",
    },
)
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
DEFAULT_PROVENANCE_RUN_CRATE_NAME = "Snakemake Provenance Run"
DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION = (
    "RO-Crate describing a Snakemake workflow run."
)


class ConfigurationEntry(TypedDict):
    index: int
    config: semantic_benchmark.ParameterSet
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


def _formal_parameter_key(part: semantic_benchmark.ParameterEntry) -> tuple[Any, ...]:
    return (
        type(part).__name__,
        part.label,
        getattr(part, "unit", None),
        getattr(part, "numerical_value", None),
        getattr(part, "string_value", None),
        getattr(part, "quantity_kind", None),
    )


def _formal_parameter_payload(
    part_id: str, part: semantic_benchmark.ParameterEntry
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "@id": part_id,
        "@type": "FormalParameter",
        "name": part.label,
    }

    unit = getattr(part, "unit", None)
    payload["additionalType"] = ""
    
    if unit is not None:
        payload["m4i:hasKindOfQuantity"] = { "@id": unit}
        
    if isinstance(part, semantic_benchmark.NumericalParameter):
        payload["defaultValue"] = part.numerical_value
    elif isinstance(part, semantic_benchmark.TextParameter):
        payload["defaultValue"] = part.string_value
    elif (
        isinstance(part, semantic_benchmark.NumericalVariable)
        and part.quantity_kind is not None
    ):
        payload["valueReference"] = part.quantity_kind

    return payload


def _add_configuration_nodes(
    crate: ROCrate,
    benchmark_object: semantic_benchmark.SemanticBenchmark,
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
    metric: semantic_benchmark.NumericalVariable,
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
    benchmark_object: semantic_benchmark.SemanticBenchmark,
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
    processing_step: semantic_benchmark.ProcessingStep,
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
    processing_steps: list[semantic_benchmark.ProcessingStep],
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _reference_id(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("@id")
    if isinstance(value, str):
        return value
    return None


def _crate_safe_id(entity_id: str | None) -> str:
    if not entity_id:
        return f"#{uuid.uuid4()}"
    if entity_id.startswith("local:"):
        return f"#{entity_id.removeprefix('local:')}"
    return entity_id


def _configure_extracted_provenance_run_metadata(
    crate: ROCrate, config_data: dict
) -> None:
    crate.metadata.extra_contexts.append(WORKFLOW_RUN_CONTEXT)
    crate.metadata.extra_terms = {"m4i:hasKindOfQuantity": M4I_HAS_KIND_OF_QUANTITY}

    rocrate_info = config_data.get("rocrate", {})
    crate.name = rocrate_info.get("name", DEFAULT_PROVENANCE_RUN_CRATE_NAME)
    crate.description = rocrate_info.get(
        "description", DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION
    )
    crate.license = rocrate_info.get("license")
    crate.metadata["conformsTo"] = ROCRATE_CONFORMS_TO
    crate.root_dataset.append_to("conformsTo", ROOT_DATASET_CONFORMS_TO)


def _add_extracted_supplemental_files(
    crate: ROCrate, provenance: ProvenanceResult
) -> None:
    for file in provenance.supplemental_files:
        crate.add_file(
            file.source_path,
            dest_path=file.dest_path,
            properties={
                "name": file.name,
                "encodingFormat": file.encoding_format,
            },
        )


def _add_extracted_provenance_files(
    crate: ROCrate,
    provenance_filename: str,
    provenance_ttl_filename: str,
) -> None:
    for file_path, encoding_format in (
        (provenance_filename, "application/ld+json"),
        (provenance_ttl_filename, "text/turtle"),
    ):
        crate.add_file(
            file_path,
            dest_path=file_path,
            properties={
                "name": file_path,
                "encodingFormat": encoding_format,
            },
        )


def _add_extracted_data_files(
    crate: ROCrate, file_nodes: dict[str, dict[str, Any]]
) -> dict[str, str]:
    file_id_map: dict[str, str] = {}
    for file_path, file_node in file_nodes.items():
        crate.add_file(
            file_path,
            dest_path=file_path,
            properties={
                "name": file_node.get("label", file_path),
                "encodingFormat": get_mime_type(file_path),
            },
        )
        source_id = file_node.get("@id")
        if source_id:
            file_id_map[source_id] = file_path
    return file_id_map


def _add_extracted_tools(
    crate: ROCrate, tools: dict[str, dict[str, Any]]
) -> dict[str, str]:
    tool_id_map: dict[str, str] = {}
    for tool_node in tools.values():
        source_id = tool_node.get("@id")
        crate_id = _crate_safe_id(source_id)
        crate.add_jsonld(
            {
                "@id": crate_id,
                "@type": "SoftwareApplication",
                "name": tool_node.get("label", crate_id),
                **(
                    {"softwareVersion": tool_node["softwareVersion"]}
                    if tool_node.get("softwareVersion")
                    else {}
                ),
            }
        )
        if source_id:
            tool_id_map[source_id] = crate_id
    return tool_id_map


def _ensure_default_software_application(crate: ROCrate) -> str:
    software_id = "#snakemake"
    if not crate.get(software_id):
        crate.add_jsonld(
            {
                "@id": software_id,
                "@type": "SoftwareApplication",
                "name": "Snakemake",
            }
        )
    return software_id


def _formal_parameter_node(
    action_id: str,
    direction: str,
    index: int,
    file_ref_id: str,
    file_id_map: dict[str, str],
    file_nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    file_entity_id = file_id_map.get(file_ref_id, _crate_safe_id(file_ref_id))
    file_node = file_nodes_by_id.get(file_ref_id, {})
    name = file_node.get("label", file_entity_id)
    action_slug = action_id.removeprefix("#")
    return {
        "@id": f"#{action_slug}-{direction}-{index}",
        "@type": "FormalParameter",
        "name": name,
        "additionalType": direction,
        "workExample": {"@id": file_entity_id},
    }


def _instrument_ids_for_step(
    step_node: dict[str, Any],
    methods_by_id: dict[str, dict[str, Any]],
    tool_id_map: dict[str, str],
    fallback_tool_id: str,
) -> list[dict[str, str]]:
    method_id = _reference_id(step_node.get("realizes method"))
    method_node = methods_by_id.get(method_id, {}) if method_id else {}
    instrument_ids = []
    for tool_ref in _as_list(method_node.get("implemented by")):
        tool_id = _reference_id(tool_ref)
        crate_tool_id = tool_id_map.get(tool_id) if tool_id else None
        if crate_tool_id:
            instrument_ids.append({"@id": crate_tool_id})
    return instrument_ids or [{"@id": fallback_tool_id}]


def _add_extracted_processing_steps_as_actions(
    crate: ROCrate,
    provenance: ProvenanceResult,
    file_id_map: dict[str, str],
    tool_id_map: dict[str, str],
    fallback_tool_id: str,
) -> None:
    file_nodes_by_id = {
        file_node["@id"]: file_node
        for file_node in provenance.file_nodes.values()
        if file_node.get("@id")
    }
    methods_by_id = {
        method_node["@id"]: method_node
        for method_node in provenance.methods.values()
        if method_node.get("@id")
    }
    action_refs: list[dict[str, str]] = []

    for step_node in provenance.processing_steps.values():
        if step_node.get("@type") != "processing step":
            continue

        action_id = _crate_safe_id(step_node.get("@id"))
        input_parameters = []
        output_parameters = []

        for direction, source_key, target in (
            ("input", "has input", input_parameters),
            ("output", "has output", output_parameters),
        ):
            for index, file_ref in enumerate(
                _as_list(step_node.get(source_key)), start=1
            ):
                file_ref_id = _reference_id(file_ref)
                if not file_ref_id:
                    continue
                parameter = _formal_parameter_node(
                    action_id=action_id,
                    direction=direction,
                    index=index,
                    file_ref_id=file_ref_id,
                    file_id_map=file_id_map,
                    file_nodes_by_id=file_nodes_by_id,
                )
                parameter_id = parameter["@id"]
                crate.add_jsonld(parameter)
                target.append({"@id": parameter_id})

        action: dict[str, Any] = {
            "@id": action_id,
            "@type": "CreateAction",
            "name": step_node.get("label", action_id),
            "instrument": _instrument_ids_for_step(
                step_node=step_node,
                methods_by_id=methods_by_id,
                tool_id_map=tool_id_map,
                fallback_tool_id=fallback_tool_id,
            ),
        }
        if step_node.get("start time"):
            action["startTime"] = step_node["start time"]
        if step_node.get("end time"):
            action["endTime"] = step_node["end time"]
        if input_parameters:
            action["object"] = input_parameters
        if output_parameters:
            action["result"] = output_parameters

        crate.add_jsonld(action)
        action_refs.append({"@id": action_id})

    if action_refs:
        crate.root_dataset.append_to("mentions", action_refs)


def _add_extracted_workflow(
    crate: ROCrate, provenance: ProvenanceResult, fallback_tool_id: str
) -> None:
    snakefile = next(
        (
            file
            for file in provenance.supplemental_files
            if Path(file.dest_path).name.lower() == "snakefile"
        ),
        None,
    )
    if not snakefile:
        return

    workflow = crate.add_workflow(
        source=snakefile.source_path,
        dest_path=snakefile.dest_path,
        lang="snakemake",
        properties={"hasPart": {"@id": fallback_tool_id}},
    )
    crate.mainEntity = {"@id": workflow.id}


def create_provenance_run_rocrate(
    provenance: ProvenanceResult,
    config_data: dict,
    provenance_filename: str = "provenance.jsonld",
    provenance_ttl_filename: str = "provenance.ttl",
    output_path: str | Path = "RO.zip",
    ro_crate_version: str = "1.1",
) -> str:
    crate = ROCrate(version=ro_crate_version)
    _configure_extracted_provenance_run_metadata(crate, config_data)
    _add_extracted_supplemental_files(crate, provenance)
    _add_extracted_provenance_files(
        crate,
        provenance_filename=provenance_filename,
        provenance_ttl_filename=provenance_ttl_filename,
    )
    file_id_map = _add_extracted_data_files(crate, provenance.file_nodes)
    tool_id_map = _add_extracted_tools(crate, provenance.tools)
    fallback_tool_id = _ensure_default_software_application(crate)
    _add_extracted_processing_steps_as_actions(
        crate=crate,
        provenance=provenance,
        file_id_map=file_id_map,
        tool_id_map=tool_id_map,
        fallback_tool_id=fallback_tool_id,
    )
    _add_extracted_workflow(crate, provenance, fallback_tool_id)
    _add_profile_creative_works(crate)

    output_path = str(output_path)
    crate.write_zip(output_path)
    return output_path


def _software_application_payload(
    benchmark_object: semantic_benchmark.SemanticBenchmark,
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
    benchmark_object: semantic_benchmark.SemanticBenchmark,
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
        "--benchmark-file",
        default=DEFAULT_BENCHMARK_FILE,
        help="Path to benchmark JSON-LD file",
    )
    parser.add_argument(
        "--simulation-result-path",
        default=DEFAULT_SIMULATION_RESULT_PATH,
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

    benchmark_object = semantic_benchmark.BenchmarkLoader(args.benchmark_file).load()
    create_main_ro(
        args.simulation_result_path,
        benchmark_object,
        output_path=args.ro_zip,
    )


if __name__ == "__main__":
    main()
