import json
from importlib import resources
from pint import UnitRegistry
from rdflib import Graph, Namespace
from rocrate.rocrate import ROCrate
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_report_plugin_metadata4ing.reporter_graph import ReporterGraph
from snakemake_report_plugin_metadata4ing.reporter_io import ReporterIO
from snakemake_report_plugin_metadata4ing.reporter_parameters import (
    ReporterParameters,
)
from snakemake_report_plugin_metadata4ing.reporter_tools import ReporterTools


class Reporter(
    ReporterGraph,
    ReporterParameters,
    ReporterTools,
    ReporterIO,
    ReporterBase,
):
    def __post_init__(self):
        self.context_data = {}

    def render(self):
        self.config_data = {}
        self.processing_steps = {}
        self.methods = {}
        self.param_counter = 0
        self.field_counter = 0
        self.param_dict = {}
        self.field_dict = {}
        self.source_dict = {}
        self.extract_dict = {}
        self.tool_counter = 0
        self._unique_fields = set()
        self.research_problem = {}
        self.tools_dict = {}
        self.child_nodes = {}
        self.conda_tools_cache = {}
        self.crate = ROCrate()
        self.benchmark_processing_step_id = ""
        self.research_problem_id = ""
        self.method_id = ""
        self.simulation_hash = ""
        self.provenance_filename = "provenance.jsonld"
        self.provenance_ttl_filename = "provenance.ttl"
        self.external_directory_name = "_EXTERNAL"
        self.unit_graph = Graph()
        self.qudt_mapping_dict = {}
        self.qudt_url = "http://qudt.org/schema/qudt/"
        self.unit_url = "http://qudt.org/vocab/unit/"
        self.mardi4nfdi_url = "https://mardi4nfdi.de/mathmoddb#"
        self.QUDT_NS = Namespace(self.qudt_url)
        self.UNIT_NS = Namespace(self.unit_url)
        self.ontologies_path = (
            resources.files("snakemake_report_plugin_metadata4ing")
            / "ontologies"
        )
        self.ureg = UnitRegistry()

        if self.settings.filename:
            self._validate_filename(str(self.settings.filename))

        self._read_config()
        self._get_context()
        self._get_qudt()
        self._create_external_directory()

        jsonld = {
            "@context": self.context_data.get("@context", {}),
            "@graph": [],
        }
        jsonld["@context"]["unit"] = self.unit_url
        jsonld["@context"]["mardi4nfdi"] = self.mardi4nfdi_url
        self._extend_rocrate_context()
        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        file_nodes = {}
        file_counter = 0

        self._add_research_problem()
        self._add_rocrate_config_data()
        self._add_benchmark_processing_step(sorted_jobs)

        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_processing_step_node(
                job, file_nodes, file_counter
            )
            self.processing_steps[job_label] = step_node
            file_counter = len(file_nodes)

        for key, value in self.param_dict.items():
            value["@id"] = key

        for d in (
            self.processing_steps,
            file_nodes,
            self.methods,
            self.param_dict,
            self.field_dict,
            self.source_dict,
            self.extract_dict,
            self.tools_dict,
            self.child_nodes,
            self.research_problem,
        ):
            jsonld["@graph"].extend(d.values())

        self.simulation_hash = self._random_hash_from_json(jsonld, 16)
        jsonld["@context"][
            "local"
        ] = f"https://local-domain.org/{self.simulation_hash}/"
        jsonld = self._add_precedes_relations(jsonld)

        with open("provenance.jsonld", "w", encoding="utf8") as f:
            json.dump(jsonld, f, indent=4, ensure_ascii=False)

        self._create_ttl_from_jsonld(jsonld)
        self._add_provenance_nodes_to_crate(jsonld)
        self._add_ro_crate_file_nodes(file_nodes)
        self._create_ro_crate_file()
        self._clean_data()
