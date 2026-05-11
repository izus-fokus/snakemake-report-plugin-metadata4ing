from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rocrate.model import ContextEntity
from rocrate.rocrate import ROCrate

try:
    from snakemake_report_plugin_metadata4ing.models import ProvenanceResult
    from snakemake_report_plugin_metadata4ing.utils import get_mime_type
except ImportError:
    from models import ProvenanceResult
    from utils import get_mime_type

RO_CRATE_PROFILE = "ro-crate-1.1"
PROVENANCE_RUN_CRATE_PROFILE = "provenance-run-crate-0.5"
SUPPORTED_PROFILE_IDENTIFIERS = {
    RO_CRATE_PROFILE,
    PROVENANCE_RUN_CRATE_PROFILE,
}

M4I_PROFILE = "https://w3id.org/nfdi4ing/metadata4ing/1.3.1"
M4I_HAS_KIND_OF_QUANTITY = "http://w3id.org/nfdi4ing/metadata4ing#hasKindOfQuantity"
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
WORKFLOW_RUN_METADATA_CONFORMS_TO = [
    {"@id": "https://w3id.org/ro/crate/1.1"},
    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
]
WORKFLOW_RUN_ROOT_CONFORMS_TO = [
    {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
    {"@id": "https://w3id.org/ro/wfrun/workflow/0.5"},
    {"@id": "https://w3id.org/ro/wfrun/provenance/0.5"},
    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
]
WORKFLOW_RUN_PROFILE_CREATIVE_WORKS = (
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
DEFAULT_PROVENANCE_RUN_CRATE_NAME = "Snakemake Provenance Run"
DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION = (
    "RO-Crate describing a Snakemake workflow run."
)


class ROCrateBuilder(ABC):
    def __init__(
        self,
        settings,
        config_data: dict,
        provenance_filename: str = "provenance.jsonld",
        provenance_ttl_filename: str = "provenance.ttl",
        ro_crate_version: str = "1.1",
        default_output_stem: str = "RO",
    ):
        self.settings = settings
        self.config_data = config_data
        self.provenance_filename = provenance_filename
        self.provenance_ttl_filename = provenance_ttl_filename
        self.ro_crate_version = ro_crate_version
        self.default_output_stem = default_output_stem
        self.crate = ROCrate(version=self.ro_crate_version)

    def write(self, provenance: ProvenanceResult) -> str:
        self.build(provenance)
        return self._write_zip(provenance)

    @abstractmethod
    def build(self, provenance: ProvenanceResult) -> None:
        pass

    def _write_zip(self, provenance: ProvenanceResult) -> str:
        crate_path = self._output_path(provenance)
        self.crate.write_zip(crate_path)
        return crate_path

    def _output_path(self, provenance: ProvenanceResult) -> str:
        if self.settings.filename:
            return f"{self.settings.filename}.zip"
        return f"{self.default_output_stem}-{provenance.simulation_hash}.zip"

    def _rocrate_config(self) -> dict[str, Any]:
        return self.config_data.get("rocrate", {})

    def _apply_rocrate_config(self) -> None:
        rocrate_info = self._rocrate_config()
        self.crate.name = rocrate_info.get("name")
        self.crate.description = rocrate_info.get("description")
        self.crate.license = rocrate_info.get("license")

    def _add_supplemental_files(self, provenance: ProvenanceResult) -> None:
        for file in provenance.supplemental_files:
            self.crate.add_file(
                file.source_path,
                dest_path=file.dest_path,
                properties={
                    "name": file.name,
                    "encodingFormat": file.encoding_format,
                },
            )

    def _add_provenance_files(
        self,
        jsonld_properties: dict[str, Any] | None = None,
        ttl_properties: dict[str, Any] | None = None,
    ) -> None:
        jsonld_properties = {
            "name": self.provenance_filename,
            "encodingFormat": "application/ld+json",
            **(jsonld_properties or {}),
        }
        ttl_properties = {
            "name": self.provenance_ttl_filename,
            "encodingFormat": "text/turtle",
            **(ttl_properties or {}),
        }
        self.crate.add_file(
            self.provenance_filename,
            dest_path=self.provenance_filename,
            properties=jsonld_properties,
        )
        self.crate.add_file(
            self.provenance_ttl_filename,
            dest_path=self.provenance_ttl_filename,
            properties=ttl_properties,
        )

    def _add_data_files(
        self, file_nodes: dict[str, dict[str, Any]]
    ) -> dict[str, str]:
        file_id_map: dict[str, str] = {}
        for file_path, file_node in file_nodes.items():
            self.crate.add_file(
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

    def _add_context_entity(
        self,
        jsonld: dict[str, Any],
        *,
        skip_existing: bool = False,
    ) -> ContextEntity | None:
        entity_id = jsonld.get("@id")
        if not entity_id or "@type" not in jsonld:
            raise ValueError(
                "Contextual entities require non-empty '@id' and '@type' values."
            )
        if self.crate.get(entity_id):
            if skip_existing:
                return None
            raise ValueError(f"Entity {entity_id!r} already exists in the RO-Crate.")

        properties = {key: value for key, value in jsonld.items() if key != "@id"}
        return self.crate.add(
            ContextEntity(
                self.crate,
                entity_id,
                properties=properties,
            )
        )


class Metadata4IngROCrateBuilder(ROCrateBuilder):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default_output_stem", "ro-crate")
        super().__init__(*args, **kwargs)

    def build(self, provenance: ProvenanceResult) -> None:
        self._extend_rocrate_context(provenance.context_data)
        self._apply_rocrate_config()

        if provenance.benchmark_processing_step_id:
            self.crate.mainEntity = {
                "@id": provenance.benchmark_processing_step_id.replace(
                    "local:", "#"
                )
            }

        self._add_supplemental_files(provenance)
        self._add_provenance_nodes_to_crate(provenance.jsonld)
        self._add_ro_crate_file_nodes(provenance.file_nodes)

    def _extend_rocrate_context(self, context_data: dict) -> None:
        metadata4ing_context = dict(context_data.get("@context", {}))
        metadata4ing_context.pop("@vocab", None)
        metadata4ing_context.pop("description", None)
        metadata4ing_context["softwareVersion"] = {"@id": "schema:softwareVersion"}
        metadata4ing_context["dataType"] = {"@id": "cr:dataType"}
        metadata4ing_context["extract"] = {"@id": "cr:extract"}
        metadata4ing_context["jsonPath"] = {"@id": "cr:jsonPath"}
        metadata4ing_context["schema"] = "http://schema.org/"
        self.crate.metadata.extra_contexts.append(metadata4ing_context)

    def _add_ro_crate_file_nodes(self, file_nodes: dict[str, dict[str, Any]]) -> None:
        self._add_provenance_files(
            jsonld_properties={
                "conformsTo": [
                    f"https://w3id.org/ro/crate/{self.ro_crate_version}",
                    M4I_PROFILE,
                ],
            }
        )
        self._add_data_files(file_nodes)

    def _add_provenance_nodes_to_crate(self, jsonld: dict[str, Any]) -> None:
        for node in jsonld["@graph"]:
            entity_id = node["@id"]
            if entity_id is None:
                continue
            self._add_context_entity(node, skip_existing=True)


class ProvenanceRunROCrateBuilder(ROCrateBuilder):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default_output_stem", "ro-crate")
        super().__init__(*args, **kwargs)

    def build(self, provenance: ProvenanceResult) -> None:
        self._configure_metadata()
        self._add_supplemental_files(provenance)
        self._add_provenance_files()
        file_id_map = self._add_data_files(provenance.file_nodes)
        tool_id_map = self._add_tools(provenance.tools)
        fallback_tool_id = self._ensure_default_software_application()
        self._add_processing_steps_as_actions(
            provenance=provenance,
            file_id_map=file_id_map,
            tool_id_map=tool_id_map,
            fallback_tool_id=fallback_tool_id,
        )
        self._add_workflow(provenance, fallback_tool_id)
        self._add_profile_creative_works()

    def _configure_metadata(self) -> None:
        self.crate.metadata.extra_contexts.append(WORKFLOW_RUN_CONTEXT)
        self.crate.metadata.extra_terms = {
            "m4i:hasKindOfQuantity": M4I_HAS_KIND_OF_QUANTITY
        }

        rocrate_info = self._rocrate_config()
        self.crate.name = rocrate_info.get("name", DEFAULT_PROVENANCE_RUN_CRATE_NAME)
        self.crate.description = rocrate_info.get(
            "description", DEFAULT_PROVENANCE_RUN_CRATE_DESCRIPTION
        )
        self.crate.license = rocrate_info.get("license")
        self.crate.metadata["conformsTo"] = WORKFLOW_RUN_METADATA_CONFORMS_TO
        self.crate.root_dataset.append_to(
            "conformsTo", WORKFLOW_RUN_ROOT_CONFORMS_TO
        )

    def _add_tools(self, tools: dict[str, dict[str, Any]]) -> dict[str, str]:
        tool_id_map: dict[str, str] = {}
        for tool_node in tools.values():
            source_id = tool_node.get("@id")
            crate_id = _crate_safe_id(source_id)
            self._add_context_entity(
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

    def _ensure_default_software_application(self) -> str:
        software_id = "#snakemake"
        if not self.crate.get(software_id):
            self._add_context_entity(
                {
                    "@id": software_id,
                    "@type": "SoftwareApplication",
                    "name": "Snakemake",
                }
            )
        return software_id

    def _add_processing_steps_as_actions(
        self,
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
                self._add_formal_parameters(
                    action_id=action_id,
                    direction=direction,
                    file_refs=_as_list(step_node.get(source_key)),
                    file_id_map=file_id_map,
                    file_nodes_by_id=file_nodes_by_id,
                    target=target,
                )

            action = self._create_action(
                step_node=step_node,
                action_id=action_id,
                input_parameters=input_parameters,
                output_parameters=output_parameters,
                methods_by_id=methods_by_id,
                tool_id_map=tool_id_map,
                fallback_tool_id=fallback_tool_id,
            )
            self._add_context_entity(action)
            action_refs.append({"@id": action_id})

        if action_refs:
            self.crate.root_dataset.append_to("mentions", action_refs)

    def _add_formal_parameters(
        self,
        action_id: str,
        direction: str,
        file_refs: list[Any],
        file_id_map: dict[str, str],
        file_nodes_by_id: dict[str, dict[str, Any]],
        target: list[dict[str, str]],
    ) -> None:
        for index, file_ref in enumerate(file_refs, start=1):
            file_ref_id = _reference_id(file_ref)
            if not file_ref_id:
                continue
            parameter = self._formal_parameter_node(
                action_id=action_id,
                direction=direction,
                index=index,
                file_ref_id=file_ref_id,
                file_id_map=file_id_map,
                file_nodes_by_id=file_nodes_by_id,
            )
            parameter_id = parameter["@id"]
            self._add_context_entity(parameter)
            target.append({"@id": parameter_id})

    def _formal_parameter_node(
        self,
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

    def _create_action(
        self,
        step_node: dict[str, Any],
        action_id: str,
        input_parameters: list[dict[str, str]],
        output_parameters: list[dict[str, str]],
        methods_by_id: dict[str, dict[str, Any]],
        tool_id_map: dict[str, str],
        fallback_tool_id: str,
    ) -> dict[str, Any]:
        action: dict[str, Any] = {
            "@id": action_id,
            "@type": "CreateAction",
            "name": step_node.get("label", action_id),
            "instrument": self._instrument_ids_for_step(
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
        return action

    def _instrument_ids_for_step(
        self,
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

    def _add_workflow(
        self, provenance: ProvenanceResult, fallback_tool_id: str
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

        workflow = self.crate.add_workflow(
            source=snakefile.source_path,
            dest_path=snakefile.dest_path,
            lang="snakemake",
            properties={"hasPart": {"@id": fallback_tool_id}},
        )
        self.crate.mainEntity = {"@id": workflow.id}

    def _add_profile_creative_works(self) -> None:
        for creative_work in WORKFLOW_RUN_PROFILE_CREATIVE_WORKS:
            self._add_context_entity(creative_work)


def rocrate_builder_for_profile(
    profile_identifier: str,
    settings,
    config_data: dict,
    provenance_filename: str = "provenance.jsonld",
    provenance_ttl_filename: str = "provenance.ttl",
) -> ROCrateBuilder:
    if profile_identifier == RO_CRATE_PROFILE:
        return Metadata4IngROCrateBuilder(
            settings=settings,
            config_data=config_data,
            provenance_filename=provenance_filename,
            provenance_ttl_filename=provenance_ttl_filename,
        )
    if profile_identifier == PROVENANCE_RUN_CRATE_PROFILE:
        return ProvenanceRunROCrateBuilder(
            settings=settings,
            config_data=config_data,
            provenance_filename=provenance_filename,
            provenance_ttl_filename=provenance_ttl_filename,
        )

    supported = ", ".join(sorted(SUPPORTED_PROFILE_IDENTIFIERS))
    raise ValueError(
        f"Unsupported profile_identifier '{profile_identifier}'. "
        f"Supported values are: {supported}."
    )


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
