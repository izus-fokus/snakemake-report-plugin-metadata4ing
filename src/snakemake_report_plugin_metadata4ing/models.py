from dataclasses import dataclass, field


@dataclass(frozen=True)
class CrateFile:
    source_path: str
    dest_path: str
    name: str
    encoding_format: str


@dataclass
class ProvenanceResult:
    jsonld: dict
    context_data: dict
    file_nodes: dict
    processing_steps: dict
    parameters: dict
    methods: dict
    tools: dict
    fields: dict
    sources: dict
    extracts: dict
    research_problem: dict
    supplemental_files: list[CrateFile] = field(default_factory=list)
    simulation_hash: str = ""
    benchmark_processing_step_id: str = ""
