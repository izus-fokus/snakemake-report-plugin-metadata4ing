"""Shared dataclasses used across provenance extraction and crate building.

These classes carry the in-memory representation of extracted provenance and
the mutable state used while constructing it.
"""

from dataclasses import dataclass, field
from typing import Any

from snakemake_report_plugin_metadata4ing.jsonld import (
    JsonLdDocument,
    JsonLdNode,
    JsonLdNodeMap,
)


@dataclass(frozen=True)
class CrateFile:
    """File scheduled to be copied into the generated RO-Crate.

    Attributes:
        source_path: Original file path on disk.
        dest_path: Destination path inside the RO-Crate.
        name: Display name recorded in metadata.
        encoding_format: MIME type or encoding format stored for the file.
    """

    source_path: str
    dest_path: str
    name: str
    encoding_format: str


@dataclass
class ProvenanceResult:
    """Final provenance payload consumed by RO-Crate builders.

    Attributes:
        jsonld: Complete provenance JSON-LD document.
        context_data: Raw ontology context document used to seed the graph.
        file_nodes: Mapping of file paths to JSON-LD file nodes.
        processing_steps: Mapping of processing-step labels to step nodes.
        parameters: Mapping of parameter IDs to parameter nodes.
        methods: Mapping of method IDs to method nodes.
        tools: Mapping of tool names or IDs to tool nodes.
        fields: Mapping of field IDs to Croissant field nodes.
        sources: Mapping of source IDs to Croissant data source nodes.
        extracts: Mapping of extract IDs to extraction nodes.
        research_problem: Mapping of research-problem IDs to problem nodes.
        supplemental_files: Files that should be included in the final crate in
            addition to the main provenance serialization.
        simulation_hash: Stable hash derived from the JSON-LD graph.
        benchmark_processing_step_id: Identifier of the synthetic benchmark step.
    """

    jsonld: JsonLdDocument
    context_data: JsonLdDocument
    file_nodes: JsonLdNodeMap
    processing_steps: JsonLdNodeMap
    parameters: JsonLdNodeMap
    methods: JsonLdNodeMap
    tools: JsonLdNodeMap
    fields: JsonLdNodeMap
    sources: JsonLdNodeMap
    extracts: JsonLdNodeMap
    research_problem: JsonLdNodeMap
    supplemental_files: list[CrateFile] = field(default_factory=list)
    simulation_hash: str = ""
    benchmark_processing_step_id: str = ""


@dataclass
class ProvenanceState:
    """Mutable in-memory state accumulated while building provenance.

    Attributes:
        processing_steps: Processing-step nodes collected so far.
        methods: Method nodes collected so far.
        parameters: Parameter nodes collected so far.
        fields: Field nodes collected so far.
        sources: Source nodes collected so far.
        extracts: Extract nodes collected so far.
        research_problem: Research-problem nodes collected so far.
        tools: Tool nodes collected so far.
        supplemental_files: Supplemental files queued for crate inclusion.
        conda_tools_cache: Cache from conda descriptors to extracted tool nodes.
        qudt_mapping: Cache from raw unit strings to resolved QUDT IDs.
        unique_fields: Keys used to prevent duplicate field/source/extract nodes.
        param_counter: Counter used to generate unique parameter IDs.
        field_counter: Counter used to generate unique field IDs.
        tool_counter: Counter used to generate unique tool IDs.
        benchmark_processing_step_id: Synthetic benchmark-step identifier.
        research_problem_id: Research-problem identifier from config data.
        simulation_hash: Final graph hash once computed.
    """

    processing_steps: JsonLdNodeMap = field(default_factory=dict)
    methods: JsonLdNodeMap = field(default_factory=dict)
    parameters: JsonLdNodeMap = field(default_factory=dict)
    fields: JsonLdNodeMap = field(default_factory=dict)
    sources: JsonLdNodeMap = field(default_factory=dict)
    extracts: JsonLdNodeMap = field(default_factory=dict)
    research_problem: JsonLdNodeMap = field(default_factory=dict)
    tools: JsonLdNodeMap = field(default_factory=dict)
    supplemental_files: dict[str, CrateFile] = field(default_factory=dict)
    conda_tools_cache: dict[Any, list[JsonLdNode]] = field(default_factory=dict)
    qudt_mapping: dict[str, str] = field(default_factory=dict)
    unique_fields: set[tuple[Any, ...]] = field(default_factory=set)
    param_counter: int = 0
    field_counter: int = 0
    tool_counter: int = 0
    benchmark_processing_step_id: str = ""
    research_problem_id: str = ""
    simulation_hash: str = ""
