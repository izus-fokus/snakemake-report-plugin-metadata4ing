"""RO-Crate builder implementations for the supported output profiles.

This module converts :class:`~snakemake_report_plugin_metadata4ing.models.ProvenanceResult`
instances into concrete RO-Crate ZIP archives. Each builder specializes in one
profile while sharing a common base class for file handling, metadata
application, and contextual-entity creation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rocrate.model import ContextEntity
from rocrate.rocrate import ROCrate

from snakemake_report_plugin_metadata4ing.jsonld import (
    JsonLdDocument,
    JsonLdNode,
    JsonLdNodeMap,
    as_list,
    crate_safe_id,
    reference_id,
)
from snakemake_report_plugin_metadata4ing.models import ProvenanceResult
from snakemake_report_plugin_metadata4ing.utils import get_mime_type

RO_CRATE_PROFILE = "ro-crate-1.1"
PROVENANCE_RUN_CRATE_PROFILE = "provenance-run-crate-0.5"
SUPPORTED_PROFILE_IDENTIFIERS = {
    RO_CRATE_PROFILE,
    PROVENANCE_RUN_CRATE_PROFILE,
}

M4I_PROFILE = "https://w3id.org/nfdi4ing/metadata4ing/1.3.1"
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
DEFAULT_RO_CRATE_LICENSE = "https://opensource.org/licenses/MIT"


class ROCrateBuilder(ABC):
    """Abstract base class for transforming provenance into an RO-Crate.

    Subclasses populate ``self.crate`` according to a selected RO-Crate
    profile, while this base class handles output naming and shared file/entity
    helpers.
    """

    def __init__(
        self,
        dag: any,
        settings,
        provenance_filename: str = "provenance.jsonld",
        provenance_ttl_filename: str = "provenance.ttl",
        ro_crate_version: str = "1.1",
        default_output_stem: str = "RO",
    ):
        """Initialize shared builder configuration and an empty crate.

        Args:
            settings: Snakemake report plugin settings object.
            provenance_filename: Filename of the serialized JSON-LD provenance
                document that will be included in the crate.
            provenance_ttl_filename: Filename of the serialized Turtle
                provenance document that will be included in the crate.
            ro_crate_version: RO-Crate version string used to initialize the
                crate object.
            default_output_stem: Default filename stem used when the user does
                not provide an explicit output name.
        """
        self.settings = settings
        self.dag = dag
        self.provenance_filename = provenance_filename
        self.provenance_ttl_filename = provenance_ttl_filename
        self.ro_crate_version = ro_crate_version
        self.default_output_stem = default_output_stem
        self.crate = ROCrate(version=self.ro_crate_version)

    def write(self, provenance: ProvenanceResult) -> str:
        """Build the crate and write it to a ZIP archive.

        Args:
            provenance: Provenance payload extracted from the workflow run.

        Returns:
            The path to the written ZIP archive.
        """
        self.build(provenance)
        return self._write_zip(provenance)

    @abstractmethod
    def build(self, provenance: ProvenanceResult) -> None:
        """Populate ``self.crate`` from the given provenance payload.

        Args:
            provenance: Provenance payload extracted from the workflow run.

        Returns:
            None. Subclasses mutate ``self.crate`` in place.
        """
        pass

    def _write_zip(self, provenance: ProvenanceResult) -> str:
        """Write the current crate to its resolved output path.

        Args:
            provenance: Provenance payload used to derive the output filename.

        Returns:
            The output path passed to :meth:`ROCrate.write_zip`.
        """
        crate_path = self._output_path(provenance)
        self.crate.write_zip(crate_path)
        return crate_path

    def _output_path(self, provenance: ProvenanceResult) -> str:
        """Resolve the output ZIP path for the generated crate.

        Args:
            provenance: Provenance payload containing the stable simulation
                hash.

        Returns:
            The ZIP filename for the generated crate.
        """
        if self.settings.filename:
            return f"{self.settings.filename}.zip"
        return f"{self.default_output_stem}-{provenance.simulation_hash}.zip"

    def _apply_rocrate_settings(self) -> None:
        """Apply user-provided name, description, and license values.

        Returns:
            None. The method mutates the root dataset metadata in ``self.crate``.
        """
        self.crate.name = self.settings.name
        self.crate.description = self.settings.description
        self.crate.license = self.settings.license

    def _add_supplemental_files(self, provenance: ProvenanceResult) -> None:
        """Add supplemental files gathered during provenance extraction.

        Args:
            provenance: Provenance payload containing supplemental file
                descriptors.

        Returns:
            None. Files are added directly to ``self.crate``.
        """
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
        """Add serialized provenance files to the crate.

        Args:
            jsonld_properties: Optional additional properties for the JSON-LD
                provenance file entity.
            ttl_properties: Optional additional properties for the Turtle
                provenance file entity.

        Returns:
            None. The two provenance files are added directly to ``self.crate``.
        """
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
        self, file_nodes: JsonLdNodeMap
    ) -> dict[str, str]:
        """Add file entities and map source node IDs to crate paths.

        Args:
            file_nodes: Mapping from original file paths to provenance file
                nodes.

        Returns:
            A mapping from provenance ``@id`` values to crate file IDs.
        """
        file_id_map: dict[str, str] = {}
        for file_path, file_node in file_nodes.items():
            if Path(file_path).is_absolute():
                continue  # Skip absolute paths; they cannot be added to the crate.
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
        jsonld: JsonLdNode,
        *,
        skip_existing: bool = False,
    ) -> ContextEntity | None:
        """Create and add a contextual entity from a JSON-LD node.

        Args:
            jsonld: JSON-LD node containing at least ``@id`` and ``@type``.
            skip_existing: When ``True``, return ``None`` instead of raising if
                an entity with the same ID already exists in the crate.

        Returns:
            The created :class:`ContextEntity`, or ``None`` when the entity
            already exists and ``skip_existing`` is enabled.

        Raises:
            ValueError: If the node is missing ``@id`` or ``@type``, or if a
                duplicate entity is encountered while ``skip_existing`` is
                ``False``.
        """
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
    """Builder for the Metadata4Ing-flavoured base RO-Crate profile.

    This profile keeps the original provenance graph inside a standard
    RO-Crate, enriched with Metadata4Ing-specific context terms.
    """

    def __init__(self, *args, **kwargs):
        """Set the default output stem for the base profile builder.

        Args:
            *args: Positional arguments forwarded to :class:`ROCrateBuilder`.
            **kwargs: Keyword arguments forwarded to :class:`ROCrateBuilder`.
        """
        kwargs.setdefault("default_output_stem", "ro-crate")
        super().__init__(*args, **kwargs)

    def build(self, provenance: ProvenanceResult) -> None:
        """Populate a base RO-Crate with provenance entities and files.

        Args:
            provenance: Provenance payload extracted from the workflow run.

        Returns:
            None. The crate is mutated in place.
        """
        self._extend_rocrate_context(provenance.context_data)
        self._apply_rocrate_settings()

        if provenance.benchmark_processing_step_id:
            self.crate.mainEntity = {
                "@id": provenance.benchmark_processing_step_id.replace(
                    "local:", "#"
                )
            }

        self._add_supplemental_files(provenance)
        self._add_provenance_nodes_to_crate(provenance.jsonld)
        self._add_ro_crate_file_nodes(provenance.file_nodes)

    def _extend_rocrate_context(self, context_data: JsonLdDocument) -> None:
        """Append Metadata4Ing terms to the RO-Crate JSON-LD context.

        Args:
            context_data: Source JSON-LD context document produced during
                provenance extraction.

        Returns:
            None. The method appends an extra context mapping to the crate
            metadata.
        """
        metadata4ing_context = dict(context_data.get("@context", {}))
        metadata4ing_context.pop("@vocab", None)
        metadata4ing_context.pop("description", None)
        metadata4ing_context["softwareVersion"] = {"@id": "schema:softwareVersion"}
        metadata4ing_context["dataType"] = {"@id": "cr:dataType"}
        metadata4ing_context["extract"] = {"@id": "cr:extract"}
        metadata4ing_context["jsonPath"] = {"@id": "cr:jsonPath"}
        metadata4ing_context["schema"] = "http://schema.org/"
        self.crate.metadata.extra_contexts.append(metadata4ing_context)

    def _add_ro_crate_file_nodes(self, file_nodes: JsonLdNodeMap) -> None:
        """Add provenance descriptors and data files for the base profile.

        Args:
            file_nodes: Mapping of file paths to provenance file nodes.

        Returns:
            None. Required file entities are added directly to the crate.
        """
        self._add_provenance_files(
            jsonld_properties={
                "conformsTo": [
                    f"https://w3id.org/ro/crate/{self.ro_crate_version}",
                    M4I_PROFILE,
                ],
            }
        )
        self._add_data_files(file_nodes)

    def _add_provenance_nodes_to_crate(self, jsonld: JsonLdDocument) -> None:
        """Copy provenance graph nodes into the crate as contextual entities.

        Args:
            jsonld: Complete provenance JSON-LD document.

        Returns:
            None. Nodes are copied into ``self.crate`` when not already present.
        """
        for node in jsonld["@graph"]:
            entity_id = node["@id"]
            if entity_id is None:
                continue
            self._add_context_entity(node, skip_existing=True)


class ProvenanceRunROCrateBuilder(ROCrateBuilder):
    """Builder for the Provenance Run Crate profile.

    This profile derives workflow, software, action, and formal-parameter
    entities from the extracted provenance graph rather than copying the graph
    directly.
    """

    def __init__(self, *args, **kwargs):
        """Set the default output stem for the provenance-run builder.

        Args:
            *args: Positional arguments forwarded to :class:`ROCrateBuilder`.
            **kwargs: Keyword arguments forwarded to :class:`ROCrateBuilder`.
        """
        kwargs.setdefault("default_output_stem", "ro-crate")
        super().__init__(*args, **kwargs)

    def build(self, provenance: ProvenanceResult) -> None:
        """Populate a provenance run crate from extracted provenance data.

        Args:
            provenance: Provenance payload extracted from the workflow run.

        Returns:
            None. The crate is mutated in place.
        """
        self._configure_metadata()
        self._add_supplemental_files(provenance)
        self._add_provenance_files()
        file_id_map = self._add_data_files(provenance.file_nodes)
        tool_id_map = self._add_tools(provenance.tools)
        fallback_tool_id = self._ensure_default_software_application()
        workflow_id = self._add_workflow(provenance, fallback_tool_id)
        self._add_processing_steps_as_actions(
            provenance=provenance,
            file_id_map=file_id_map,
            tool_id_map=tool_id_map,
            fallback_tool_id=fallback_tool_id,
            workflow_id=workflow_id,
        )
        self._add_profile_creative_works()

    def _configure_metadata(self) -> None:
        """Set metadata fields required by the workflow run profiles.

        Returns:
            None. The method mutates the crate metadata and root dataset.
        """
        self.crate.metadata.extra_contexts.append(WORKFLOW_RUN_CONTEXT)

        self.crate.name = self.settings.name
        self.crate.description = self.settings.description
        self.crate.license = self.settings.license
        self.crate.metadata["conformsTo"] = WORKFLOW_RUN_METADATA_CONFORMS_TO
        self.crate.root_dataset.append_to(
            "conformsTo", WORKFLOW_RUN_ROOT_CONFORMS_TO
        )

    def _add_tools(self, tools: dict[str, dict[str, Any]]) -> dict[str, str]:
        """Add tool entities and map source tool IDs to crate IDs.

        Args:
            tools: Provenance tool-node mapping.

        Returns:
            A mapping from provenance tool IDs to crate tool IDs.
        """
        tool_id_map: dict[str, str] = {}
        for tool_node in tools.values():
            source_id = tool_node.get("@id")
            crate_id = crate_safe_id(source_id)
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
        """Ensure the crate contains a fallback Snakemake software entity.

        Returns:
            The crate identifier of the fallback Snakemake software entity.
        """
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
        workflow_id: str | None,
    ) -> None:
        """Translate processing steps into RO-Crate action entities.

        Args:
            provenance: Complete provenance payload.
            file_id_map: Mapping from provenance file IDs to crate file IDs.
            tool_id_map: Mapping from provenance tool IDs to crate tool IDs.
            fallback_tool_id: Crate ID of the fallback software entity.
            workflow_id: Crate ID of the main workflow entity, when present.

        Returns:
            None. Action, value, and parameter entities are added to the crate.
        """
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

            action_id = crate_safe_id(step_node.get("@id"))
            input_parameters = []
            output_parameters = []

            for direction, source_key, target in (
                ("input", "has input", input_parameters),
                ("output", "has output", output_parameters),
            ):
                self._add_formal_parameters(
                    action_id=action_id,
                    direction=direction,
                    file_refs=as_list(step_node.get(source_key)),
                    file_id_map=file_id_map,
                    file_nodes_by_id=file_nodes_by_id,
                    workflow_id=workflow_id,
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
        workflow_id: str | None,
        target: list[dict[str, str]],
    ) -> None:
        """Create action value and formal parameter entities for an edge list.

        Args:
            action_id: Crate action identifier to which the values belong.
            direction: Parameter direction such as ``input`` or ``output``.
            file_refs: File references taken from provenance step nodes.
            file_id_map: Mapping from provenance file IDs to crate file IDs.
            file_nodes_by_id: File-node lookup keyed by provenance ``@id``.
            workflow_id: Crate ID of the main workflow entity, when present.
            target: List that receives the generated value references.

        Returns:
            None. Generated references are appended to ``target``.
        """
        for index, file_ref in enumerate(file_refs, start=1):
            file_ref_id = reference_id(file_ref)
            if not file_ref_id:
                continue
            parameter = self._add_formal_parameter(
                action_id=action_id,
                direction=direction,
                index=index,
                file_ref_id=file_ref_id,
                file_id_map=file_id_map,
                file_nodes_by_id=file_nodes_by_id,
                workflow_id=workflow_id,
            )
            parameter_id = parameter.id
            value_ref = self._link_action_value_to_parameter(
                action_id=action_id,
                direction=direction,
                index=index,
                file_ref=file_ref,
                file_ref_id=file_ref_id,
                parameter_id=parameter_id,
                file_id_map=file_id_map,
                file_nodes_by_id=file_nodes_by_id,
            )
            target.append(value_ref)

    def _add_formal_parameter(
        self,
        action_id: str,
        direction: str,
        index: int,
        file_ref_id: str,
        file_id_map: dict[str, str],
        file_nodes_by_id: dict[str, dict[str, Any]],
        workflow_id: str | None,
    ) -> Any:
        """Add a formal parameter entity for an action edge.

        Args:
            action_id: Crate action identifier that owns the parameter.
            direction: Parameter direction such as ``input`` or ``output``.
            index: One-based position within the direction-specific parameter
                list.
            file_ref_id: Provenance identifier of the referenced file.
            file_id_map: Mapping from provenance file IDs to crate file IDs.
            file_nodes_by_id: File-node lookup keyed by provenance ``@id``.
            workflow_id: Crate ID of the main workflow entity, when present.

        Returns:
            The created RO-Crate FormalParameter entity.
        """
        file_entity_id = file_id_map.get(file_ref_id, crate_safe_id(file_ref_id))
        file_node = file_nodes_by_id.get(file_ref_id, {})
        name = file_node.get("label", file_entity_id)
        action_slug = action_id.removeprefix("#")
        properties = {}
        if workflow_id:
            properties[direction] = {"@id": workflow_id}
        return self.crate.add_formal_parameter(
            name=name,
            additionalType=direction,
            identifier=f"#{action_slug}-{direction}-{index}",
            properties=properties,
        )

    def _link_action_value_to_parameter(
        self,
        action_id: str,
        direction: str,
        index: int,
        file_ref: Any,
        file_ref_id: str,
        parameter_id: str,
        file_id_map: dict[str, str],
        file_nodes_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, str]:
        """Link the action-side value node to its formal parameter.

        Args:
            action_id: Crate action identifier that owns the value.
            direction: Parameter direction such as ``input`` or ``output``.
            index: One-based position within the direction-specific value list.
            file_ref: Original value reference from the provenance step node.
            file_ref_id: Provenance identifier of the referenced value.
            parameter_id: Crate identifier of the formal parameter.
            file_id_map: Mapping from provenance file IDs to crate file IDs.
            file_nodes_by_id: File-node lookup keyed by provenance ``@id``.

        Returns:
            A JSON-LD reference to the action-side value node.
        """
        if file_ref_id in file_id_map or file_ref_id in file_nodes_by_id:
            file_entity_id = file_id_map.get(file_ref_id, crate_safe_id(file_ref_id))
            file_entity = self.crate.get(file_entity_id)
            if file_entity:
                file_entity.append_to("exampleOfWork", {"@id": parameter_id})
            return {"@id": file_entity_id}

        value_id = self._property_value_id(
            action_id=action_id,
            direction=direction,
            index=index,
        )
        value_node = {
            "@id": value_id,
            "@type": "PropertyValue",
            "name": str(file_ref_id),
            "value": file_ref_id,
            "exampleOfWork": {"@id": parameter_id},
        }
        self._add_context_entity(value_node)
        return {"@id": value_id}

    def _property_value_id(self, action_id: str, direction: str, index: int) -> str:
        """Return a stable ID for a non-file action parameter value."""
        action_slug = action_id.removeprefix("#")
        return f"#{action_slug}-{direction}-{index}-value"

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
        """Build a ``CreateAction`` node from a processing-step node.

        Args:
            step_node: Provenance processing-step node.
            action_id: Target crate identifier for the action.
            input_parameters: File or PropertyValue references representing
                action inputs.
            output_parameters: File or PropertyValue references representing
                action outputs.
            methods_by_id: Method-node lookup keyed by provenance ``@id``.
            tool_id_map: Mapping from provenance tool IDs to crate tool IDs.
            fallback_tool_id: Crate ID of the fallback software entity.

        Returns:
            A JSON-LD action node ready to be added to the crate.
        """
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
        """Resolve the software instruments associated with a workflow step.

        Args:
            step_node: Provenance processing-step node.
            methods_by_id: Method-node lookup keyed by provenance ``@id``.
            tool_id_map: Mapping from provenance tool IDs to crate tool IDs.
            fallback_tool_id: Crate ID of the fallback software entity.

        Returns:
            A list of JSON-LD references to software entities. Falls back to
            the Snakemake software entity when no explicit tools are found.
        """
        method_id = reference_id(step_node.get("realizes method"))
        method_node = methods_by_id.get(method_id, {}) if method_id else {}
        instrument_ids = []
        for tool_ref in as_list(method_node.get("implemented by")):
            tool_id = reference_id(tool_ref)
            crate_tool_id = tool_id_map.get(tool_id) if tool_id else None
            if crate_tool_id:
                instrument_ids.append({"@id": crate_tool_id})
        return instrument_ids or [{"@id": fallback_tool_id}]

    def _add_workflow(
        self, provenance: ProvenanceResult, fallback_tool_id: str
    ) -> str | None:
        """Add the Snakefile as the main workflow entity when available.

        Args:
            provenance: Provenance payload containing supplemental files.
            fallback_tool_id: Crate ID of the fallback software entity to link
                via ``hasPart``.

        Returns:
            The workflow entity ID, or ``None`` when no Snakefile is available.
        """
        snakefile = self.dag.workflow.main_snakefile

        if not snakefile:
            return None

        workflow_path = Path(snakefile)

        workflow = self.crate.add_workflow(
            source=workflow_path,
            dest_path=workflow_path.name,
            lang="snakemake",
            main=True,
            fetch_remote=False,
            properties={"hasPart": {"@id": fallback_tool_id}},
            gen_cwl=False,
        )
        self.crate.mainEntity = {"@id": workflow.id}
        return workflow.id

    def _add_profile_creative_works(self) -> None:
        """Add profile descriptors referenced by ``conformsTo`` statements.

        Returns:
            None. CreativeWork entities are added to the crate in place.
        """
        for creative_work in WORKFLOW_RUN_PROFILE_CREATIVE_WORKS:
            self._add_context_entity(creative_work)


def rocrate_builder_for_profile(
    dag: any,
    profile_identifier: str,
    settings: any,
    provenance_filename: str = "provenance.jsonld",
    provenance_ttl_filename: str = "provenance.ttl",
) -> ROCrateBuilder:
    """Return the builder implementation matching a profile identifier.

    Args:
        profile_identifier: Selected RO-Crate profile identifier.
        settings: Snakemake report plugin settings object.
        provenance_filename: Filename of the serialized JSON-LD provenance file.
        provenance_ttl_filename: Filename of the serialized Turtle provenance
            file.

    Returns:
        An initialized builder instance for the requested profile.

    Raises:
        ValueError: If the profile identifier is not supported.
    """
    if profile_identifier == RO_CRATE_PROFILE:
        return Metadata4IngROCrateBuilder(
            dag=dag,
            settings=settings,
            provenance_filename=provenance_filename,
            provenance_ttl_filename=provenance_ttl_filename,
        )
    if profile_identifier == PROVENANCE_RUN_CRATE_PROFILE:
        return ProvenanceRunROCrateBuilder(
            dag=dag,
            settings=settings,
            provenance_filename=provenance_filename,
            provenance_ttl_filename=provenance_ttl_filename,
        )

    supported = ", ".join(sorted(SUPPORTED_PROFILE_IDENTIFIERS))
    raise ValueError(
        f"Unsupported profile_identifier '{profile_identifier}'. "
        f"Supported values are: {supported}."
    )
