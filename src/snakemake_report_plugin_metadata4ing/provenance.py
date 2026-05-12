"""Build intermediate provenance data from Snakemake execution metadata.

The classes in this module transform Snakemake runtime objects, workflow
configuration, and optional parameter-extractor output into an intermediate
JSON-LD representation. That representation is later consumed by the
RO-Crate builders to create the final archive.
"""

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rdflib import Graph

from snakemake_report_plugin_metadata4ing.jsonld import (
    JsonLdNode,
    JsonLdNodeMap,
)
from snakemake_report_plugin_metadata4ing.models import (
    ProvenanceResult,
    ProvenanceState,
)
from snakemake_report_plugin_metadata4ing.ontology_resources import OntologyResources
from snakemake_report_plugin_metadata4ing.parameter_extraction import (
    ParameterExtractorRunner,
)
from snakemake_report_plugin_metadata4ing.provenance_files import FileProvenanceHelpers
from snakemake_report_plugin_metadata4ing.provenance_graph import ProvenanceGraphHelpers
from snakemake_report_plugin_metadata4ing.provenance_jobs import JobMetadataHelpers
from snakemake_report_plugin_metadata4ing.provenance_parameters import (
    ParameterProvenanceHelpers,
)
from snakemake_report_plugin_metadata4ing.tool_resolver import ToolResolver


class ProvenanceBuilder(
    FileProvenanceHelpers,
    JobMetadataHelpers,
    ParameterProvenanceHelpers,
    ProvenanceGraphHelpers,
):
    """Build an intermediate provenance graph from Snakemake execution data.

    The builder walks completed jobs, derives processing-step, method, file,
    parameter, tool, and research-problem nodes, and returns a
    :class:`ProvenanceResult` object containing both the assembled JSON-LD
    document and the registries used to build it.
    """

    def __init__(
        self,
        jobs,
        dag,
        settings,
        config_data: dict,
        provenance_filename: str = "provenance.jsonld",
        provenance_ttl_filename: str = "provenance.ttl",
        external_directory_name: str = "_EXTERNAL",
    ):
        """Initialize the builder with Snakemake runtime objects and config.

        Args:
            jobs: Iterable of Snakemake job records with timing information.
            dag: Snakemake DAG object used to resolve rule inputs, shell
                commands, and conda environments.
            settings: Plugin settings object. Only selected attributes are used,
                including an optional ``paramscript`` path.
            config_data: Parsed plugin configuration dictionary.
            provenance_filename: Output filename for the generated JSON-LD
                document.
            provenance_ttl_filename: Output filename for the generated Turtle
                serialization.
            external_directory_name: Working directory name used for copied
                files that live outside the current report directory.

        Returns:
            None.
        """
        self.jobs = jobs
        self.dag = dag
        self.settings = settings
        self.config_data = config_data
        self.provenance_filename = provenance_filename
        self.provenance_ttl_filename = provenance_ttl_filename
        self.external_directory_name = external_directory_name
        self.state = ProvenanceState()
        self.resources = OntologyResources()
        self.parameter_extractor = ParameterExtractorRunner(
            getattr(settings, "paramscript", None)
        )
        self.tool_resolver = ToolResolver()

    def build(self) -> ProvenanceResult:
        """Build the complete intermediate provenance payload.

        Returns:
            ProvenanceResult: Container with the assembled JSON-LD document,
            supporting node registries, supplemental file records, and the
            derived simulation hash used for local identifiers.
        """
        self.state = ProvenanceState()
        context_data = self.resources.load_context()
        self.resources.load_qudt_graph()

        jsonld_context = dict(context_data.get("@context", {}))
        jsonld_context.pop("@vocab", None)
        jsonld_context.pop("description", None)
        jsonld = {
            "@context": jsonld_context,
            "@graph": [],
        }
        jsonld["@context"]["unit"] = self.resources.unit_url
        jsonld["@context"]["mardi4nfdi"] = self.resources.mardi4nfdi_url

        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        file_nodes: JsonLdNodeMap = {}

        self._add_research_problem()
        self._add_benchmark_processing_step(sorted_jobs)

        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_processing_step_node(job, file_nodes)
            self.state.processing_steps[job_label] = step_node

        for key, value in self.state.parameters.items():
            value["@id"] = key

        for graph_fragment in (
            self.state.processing_steps,
            file_nodes,
            self.state.methods,
            self.state.parameters,
            self.state.fields,
            self.state.sources,
            self.state.extracts,
            self.state.tools,
            self.state.research_problem,
        ):
            jsonld["@graph"].extend(graph_fragment.values())

        self.state.simulation_hash = self._random_hash_from_json(jsonld, 16)
        jsonld["@context"][
            "local"
        ] = f"https://local-domain.org/{self.state.simulation_hash}/"
        jsonld = self._add_precedes_relations(jsonld)

        return ProvenanceResult(
            jsonld=jsonld,
            context_data=context_data,
            file_nodes=file_nodes,
            processing_steps=self.state.processing_steps,
            parameters=self.state.parameters,
            methods=self.state.methods,
            tools=self.state.tools,
            fields=self.state.fields,
            sources=self.state.sources,
            extracts=self.state.extracts,
            research_problem=self.state.research_problem,
            supplemental_files=list(self.state.supplemental_files.values()),
            simulation_hash=self.state.simulation_hash,
            benchmark_processing_step_id=self.state.benchmark_processing_step_id,
        )

    def write_files(self, provenance: ProvenanceResult) -> None:
        """Serialize provenance output to JSON-LD and Turtle files.

        Args:
            provenance: Provenance result returned by :meth:`build`.

        Returns:
            None.
        """
        with open(self.provenance_filename, "w", encoding="utf8") as f:
            json.dump(provenance.jsonld, f, indent=4, ensure_ascii=False)

        Graph().parse(data=provenance.jsonld, format="json-ld").serialize(
            self.provenance_ttl_filename, format="ttl"
        )

    def create_external_directory(self):
        """Create a clean workspace for copied external file references.

        Returns:
            None.
        """
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def workspace(self) -> Iterator[None]:
        """Provide a temporary workspace lifecycle around provenance work.

        Yields:
            None: Control returns to the caller while the external workspace is
            available.
        """
        self.create_external_directory()
        try:
            yield
        finally:
            self.clean_data()

    def clean_data(self):
        """Remove temporary workspace content and serialized provenance files.

        Returns:
            None.
        """
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)

        for file_name in (self.provenance_filename, self.provenance_ttl_filename):
            if Path(file_name).exists():
                os.remove(file_name)

    def _create_processing_step_node(
        self, job, file_nodes: JsonLdNodeMap
    ) -> JsonLdNode:
        """Create the processing-step node for one executed Snakemake job.

        Args:
            job: Snakemake job record with rule name, job identifier, outputs,
                and timing information.
            file_nodes: Shared registry of already-created file nodes.

        Returns:
            JsonLdNode: Processing-step node with input/output references and a
            linked method node.
        """
        node = {
            "@id": f"local:processing_step_{job.job.jobid}",
            "@type": "processing step",
            "label": f"{job.rule}_{job.job.jobid}",
            "start time": self._get_time_str(job.starttime),
            "end time": self._get_time_str(job.endtime),
            "has input": [],
            "has output": [],
            "realizes method": [],
            "part of": {"@id": self.state.benchmark_processing_step_id},
        }
        self._add_shell_supplemental_files(job)
        optional_fields = self._method_optional_fields(job)
        self._populate_processing_step_files(
            job=job,
            node=node,
            file_nodes=file_nodes,
            optional_fields=optional_fields,
        )
        node["realizes method"] = {"@id": self._create_method_node(job, optional_fields)}
        self._add_snakefile_supplemental_file()
        return node

    def _create_method_node(self, job, optional_fields: JsonLdNode) -> str:
        """Create and register the method node backing one processing step.

        Args:
            job: Job whose rule name and identifier determine the method label
                and identifier.
            optional_fields: Additional method properties to merge into the
                created node.

        Returns:
            str: Local identifier of the created method node.
        """
        method_id = f"local:method_{job.rule}_{job.job.jobid}"
        self.state.methods[method_id] = {
            "@id": method_id,
            "@type": "method",
            "label": f"{job.rule}_{job.job.jobid}",
            **optional_fields,
        }
        return method_id
