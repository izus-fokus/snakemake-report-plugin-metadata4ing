import json
from rdflib import Graph, Namespace


class ReporterGraph:
    def _create_processing_step_node(self, job, files_dict, file_counter):
        node = {
            "@id": f"local:processing_step_{job.job.jobid}",
            "@type": "processing step",
            "label": f"{job.rule}_{job.job.jobid}",
            "start time": self._get_time_str(job.starttime),
            "end time": self._get_time_str(job.endtime),
            "has input": [],
            "has output": [],
            "realizes method": [],
            "part of": {"@id": self.benchmark_processing_step_id},
        }

        input_files = [
            f
            for j in self.dag.jobs
            if j.jobid == job.job.jobid
            for f in j.input
        ]

        conda_files = [
            j.conda_env for j in self.dag.jobs if j.jobid == job.job.jobid
        ]

        shell_cmds = [
            j.shellcmd
            for j in self.dag.jobs
            if j.jobid == job.job.jobid and j.shellcmd
        ]

        for shell_cmd_file in shell_cmds:
            script_file, _ = self._extract_script_and_files(shell_cmd_file)
            if script_file:
                resolve_shell_path = self._copy_external_relative_files(
                    script_file
                )
                _ = self.crate.add_file(
                    resolve_shell_path,
                    dest_path=resolve_shell_path,
                    properties={
                        "name": resolve_shell_path,
                        "encodingFormat": self._get_mime_type(
                            resolve_shell_path
                        ),
                    },
                )
        optional_fields = {}
        tools = {}
        for conda_file in conda_files:
            if conda_file:
                if conda_file in self.conda_tools_cache:
                    tools = self.conda_tools_cache[conda_file]
                else:
                    tools = self._add_tools(conda_file.content)
                    self.conda_tools_cache[conda_file] = tools

        new_method_node_id = f"local:method_{job.rule}_{job.job.jobid}"

        if tools:
            optional_fields["implemented by"] = [
                {"@id": tool["@id"]} for tool in tools
            ]

        for file, source in [(f, "input") for f in input_files] + [
            (f, "output") for f in job.output
        ]:
            if not self._is_file(file):
                continue
            file_node, file_counter = self._add_file(
                file, files_dict, file_counter
            )
            if source == "input":
                node["has input"].append({"@id": file_node["@id"]})
            else:
                node["has output"].append({"@id": file_node["@id"]})
            if self.settings.paramscript:
                metadata = self._extract_parameters_from_paramscript(
                    job.rule, file, file_node
                )
                rule_data = metadata.get(job.rule, {})
                for k in ("has parameter", "investigates"):
                    if k in rule_data:
                        optional_fields.setdefault(k, []).append(rule_data[k])
            elif self.settings.benchmarkfile:
                metadata = self._extract_parameters_from_benchmark(
                    job.rule, file, file_node
                )
                rule_data = metadata.get(job.rule, {})
                for k in ("has parameter", "investigates"):
                    if k in rule_data:
                        optional_fields.setdefault(k, []).append(rule_data[k])

        self.methods[new_method_node_id] = {
            "@id": new_method_node_id,
            "@type": "method",
            "label": f"{job.rule}_{job.job.jobid}",
            **optional_fields,
        }
        node["realizes method"] = {"@id": new_method_node_id}

        snakefile, snakepath = self._find_snakefile()

        if snakefile:
            _ = self.crate.add_file(
                snakefile,
                dest_path=snakepath,
                properties={
                    "name": snakefile,
                    "encodingFormat": "text/x-python",
                },
            )

        return node

    def _add_file(self, file_path, file_dict, counter):
        resolved_path = self._copy_external_relative_files(file_path)
        if resolved_path not in file_dict:
            file_dict[resolved_path] = {
                "@id": f"local:file_{counter}",
                "@type": "cr:FileObject",
                "label": resolved_path,
            }
            counter += 1
        return file_dict[resolved_path], counter

    def _add_research_problem(self):
        if "researchProblem" in self.config_data:
            self.research_problem_id = f"local:research_problem"
            research_problem = {
                "@id": self.research_problem_id,
                "@type": "mardi4nfdi:ResearchProblem",
            }
            for key, value in self.config_data["researchProblem"].items():
                property_key = f"{key.replace(' ', '_').lower()}"
                research_problem[property_key] = value
            self.research_problem[self.research_problem_id] = research_problem

    def _add_benchmark_processing_step(self, sorted_jobs):
        self.benchmark_processing_step_id = f"local:processing_step_benchmark"
        self.crate.mainEntity = {
            "@id": self.benchmark_processing_step_id.replace("local:", "#")
        }
        earliest_start = min(item.starttime for item in sorted_jobs)
        latest_end = max(item.endtime for item in sorted_jobs)
        benchmark_node = {
            "@id": self.benchmark_processing_step_id,
            "@type": "processing step",
            "label": "benchmark",
            "start time": self._get_time_str(earliest_start),
            "end time": self._get_time_str(latest_end),
            "has input": [],
            "has output": [],
            "has parameter": [],
            "investigates": (
                {"@id": self.research_problem_id}
                if self.research_problem_id
                else []
            ),
        }
        self.processing_steps[id] = benchmark_node

    def _add_precedes_relations(self, jsonld_data: dict) -> dict:
        g = Graph()
        g.parse(data=json.dumps(jsonld_data), format="json-ld")
        SCHEMA = Namespace("https://schema.org/")
        new_relations = []
        for a, _, f1 in g.triples((None, SCHEMA.result, None)):
            for b, _, f2 in g.triples((None, SCHEMA.object, None)):
                if f1 == f2:
                    local_a = self._get_local_id(str(a))
                    local_b = self._get_local_id(str(b))
                    if local_a != local_b:
                        new_relations.append((local_a, local_b))

        graph_nodes = jsonld_data.get("@graph", [])
        id_to_node = {
            self._get_local_id(node["@id"]): node
            for node in graph_nodes
            if "@id" in node
        }

        for source_id, target_id in new_relations:
            source_node = id_to_node.get(source_id)
            if not source_node:
                continue
            key = "precedes"
            existing = source_node.get(key)
            new_link = {"@id": f"local:{target_id}"}
            if not existing:
                source_node[key] = [new_link]
            else:
                if isinstance(existing, dict) or not isinstance(existing, list):
                    existing = [existing]
                    source_node[key] = existing

                if new_link not in existing:
                    existing.append(new_link)

        return jsonld_data

    def _get_local_id(self, iri: str) -> str:
        local = iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if local.startswith("local:"):
            local = local.replace("local:", "")
        return local
