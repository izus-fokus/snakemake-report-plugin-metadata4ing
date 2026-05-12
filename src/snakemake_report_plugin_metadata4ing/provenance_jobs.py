"""Job and software-tool helpers for provenance building."""

from typing import Any

from snakemake_report_plugin_metadata4ing.jsonld import JsonLdNode


class JobMetadataHelpers:
    """Helpers that read Snakemake job metadata and resolve tool nodes."""

    def _job_input_files(self, job) -> list[str]:
        """Collect input file paths for a job from the DAG."""
        return [
            file_path
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
            for file_path in dag_job.input
        ]

    def _job_conda_files(self, job) -> list[Any]:
        """Collect conda environment descriptors for a job."""
        return [
            dag_job.conda_env
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
        ]

    def _job_shell_commands(self, job) -> list[str]:
        """Collect shell commands associated with a job."""
        return [
            dag_job.shellcmd
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid and dag_job.shellcmd
        ]

    def _method_optional_fields(self, job) -> JsonLdNode:
        """Build optional method properties inferred from a job."""
        optional_fields: JsonLdNode = {}
        tools = self._job_tools(job)
        if tools:
            optional_fields["implemented by"] = [
                {"@id": tool["@id"]} for tool in tools
            ]
        return optional_fields

    def _job_tools(self, job) -> list[JsonLdNode]:
        """Resolve software-tool nodes associated with a job."""
        tools: list[JsonLdNode] = []
        for conda_file in self._job_conda_files(job):
            if not conda_file:
                continue
            if conda_file in self.state.conda_tools_cache:
                tools = self.state.conda_tools_cache[conda_file]
                continue
            tools = self._add_tools(conda_file.content)
            self.state.conda_tools_cache[conda_file] = tools
        return tools

    def _add_tools(self, env_file_content: str) -> list[JsonLdNode]:
        """Register tool nodes derived from a conda environment file."""
        tools_list = []
        tools = self.tool_resolver.extract_tools_from_yaml(env_file_content)
        if tools:
            for name, version in tools.items():
                if name not in self.state.tools:
                    item = {
                        "@id": f"local:tool_{self.state.tool_counter}",
                        "@type": "schema:SoftwareApplication",
                        "label": name,
                        **({"softwareVersion": version} if version else {}),
                    }
                    self.state.tools[name] = item
                    self.state.tool_counter += 1
                    tools_list.append(item)
                else:
                    tools_list.append(self.state.tools[name])
        return tools_list
