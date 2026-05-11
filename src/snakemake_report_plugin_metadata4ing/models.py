from dataclasses import dataclass, field
from typing import Any

from snakemake_report_plugin_metadata4ing.jsonld import (
    JsonLdDocument,
    JsonLdNode,
    JsonLdNodeMap,
)


@dataclass(frozen=True)
class CrateFile:
    source_path: str
    dest_path: str
    name: str
    encoding_format: str


@dataclass
class ProvenanceResult:
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
