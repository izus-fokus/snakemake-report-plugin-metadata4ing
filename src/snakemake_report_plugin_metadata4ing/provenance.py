import hashlib
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Optional

import yaml
from pint import UnitRegistry
from rdflib import Graph, Namespace

from snakemake_report_plugin_metadata4ing.jsonld import (
    JsonLdDocument,
    JsonLdNode,
    JsonLdNodeMap,
)
from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)
from snakemake_report_plugin_metadata4ing.models import (
    CrateFile,
    ProvenanceResult,
    ProvenanceState,
)
from snakemake_report_plugin_metadata4ing.utils import get_mime_type


class OntologyResources:
    def __init__(self) -> None:
        self.context_data: JsonLdDocument | None = None
        self.unit_graph = Graph()
        self._qudt_loaded = False
        self._qudt_mapping: dict[str, str] | None = None
        self.qudt_url = "http://qudt.org/schema/qudt/"
        self.unit_url = "http://qudt.org/vocab/unit/"
        self.mardi4nfdi_url = "https://mardi4nfdi.de/mathmoddb#"
        self.ureg = UnitRegistry()

    def load_context(self) -> JsonLdDocument:
        if self.context_data is None:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("metadata4ing.jsonld").open("r", encoding="utf-8") as handle:
                self.context_data = json.load(handle)
        return self.context_data

    def load_qudt_graph(self) -> Graph:
        if not self._qudt_loaded:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("qudt.ttl").open("r", encoding="utf-8") as handle:
                self.unit_graph.parse(data=handle.read(), format="ttl")
            self._qudt_loaded = True
        return self.unit_graph

    def get_qudt_unit(self, unit: str) -> str | None:
        if self._qudt_mapping is None:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("qudt-mapping.json").open("r", encoding="utf-8") as handle:
                self._qudt_mapping = json.load(handle)
        pint_unit = self.ureg.parse_units(unit)
        if str(pint_unit) in self._qudt_mapping:
            return f"unit:{self._qudt_mapping[str(pint_unit)]}"
        return unit


class ParameterExtractorRunner:
    def __init__(self, script_path: Path | None) -> None:
        self.script_path = script_path.expanduser().resolve() if script_path else None
        self._extractor = None

    @property
    def enabled(self) -> bool:
        return self.script_path is not None

    def extract(self, rule_name: str, file_path: str) -> dict[str, Any]:
        if not self.enabled:
            return {}
        extractor = self._load_extractor()
        result = extractor.extract_params(rule_name, file_path)
        return self.validate_output(result) if result else {}

    def _load_extractor(self):
        if self._extractor is not None:
            return self._extractor
        if self.script_path is None or not self.script_path.exists():
            raise FileNotFoundError(f"Script not found: {self.script_path}")

        spec = importlib.util.spec_from_file_location(
            "extractor_module", str(self.script_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ParameterExtractorInterface)
                and obj is not ParameterExtractorInterface
            ):
                self._extractor = obj()
                return self._extractor

        raise ImportError("No subclass of ParameterExtractorInterface found in script")

    @staticmethod
    def validate_output(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")

        def _validate_entry(entry_key, entry_value):
            if not isinstance(entry_key, str):
                raise TypeError(f"Key '{entry_key}' must be a string.")
            if not isinstance(entry_value, dict):
                raise TypeError(
                    f"Value for key '{entry_key}' must be a dictionary."
                )

            required_keys = ["value", "unit", "json-path", "data-type"]
            for required_key in required_keys:
                if required_key not in entry_value:
                    raise ValueError(
                        f"Missing key '{required_key}' in value for '{entry_key}'."
                    )

            if entry_value["unit"] and not isinstance(entry_value["unit"], str):
                raise TypeError(f"'unit' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["json-path"], str):
                raise TypeError(f"'json-path' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["data-type"], str):
                raise TypeError(f"'data-type' for '{entry_key}' must be a string.")

        def _validate_section(section_name, section_content):
            if not isinstance(section_content, list):
                raise TypeError(f"'{section_name}' must be a list.")
            for item in section_content:
                if not isinstance(item, dict):
                    raise TypeError(
                        f"Each item in '{section_name}' must be a dictionary."
                    )
                if len(item) != 1:
                    raise ValueError(
                        f"Each item in '{section_name}' must have exactly one "
                        f"key, found {len(item)}."
                    )
                inner_key, inner_value = next(iter(item.items()))
                _validate_entry(inner_key, inner_value)

        for root_key, root_value in result.items():
            if not isinstance(root_key, str):
                raise TypeError(f"Root key '{root_key}' must be a string.")
            if not isinstance(root_value, dict):
                raise TypeError(
                    f"Root value for '{root_key}' must be a dictionary."
                )

            if not any(
                key in root_value for key in ["has parameter", "investigates"]
            ):
                raise ValueError(
                    f"Root key '{root_key}' must contain at least "
                    "'has parameter' or 'investigates'."
                )

            for section in ["has parameter", "investigates"]:
                if section in root_value:
                    _validate_section(section, root_value[section])

        return result


class ToolResolver:
    def __init__(self) -> None:
        self._envs: dict[str, str] | None = None
        self._packages_by_env: dict[str, dict[str, str]] = {}

    def extract_tools_from_yaml(self, env_file_content: str) -> dict[str, str | None]:
        results: dict[str, str | None] = {}
        found_targets = set()
        parsed = yaml.safe_load(env_file_content) or {}
        dependencies = parsed.get("dependencies", [])

        version_pattern = re.compile(r"([a-zA-Z0-9_.\-]+)([=><!~]+.*)?")

        for dep in dependencies:
            if isinstance(dep, str):
                match = version_pattern.match(dep.strip())
                if not match:
                    continue
                pkg_name = match.group(1).lower()
                version = match.group(2).lstrip("=") if match.group(2) else None
                results[pkg_name] = version
                found_targets.add(pkg_name)
            elif isinstance(dep, dict):
                for _, pkgs in dep.items():
                    for pkg in pkgs:
                        match = version_pattern.match(pkg.strip())
                        if not match:
                            continue
                        pkg_name = match.group(1).lower()
                        version = (
                            match.group(2).lstrip("=") if match.group(2) else None
                        )
                        results[pkg_name] = version
                        found_targets.add(pkg_name)

        selected_env_pkgs = None
        for _, env_path in self._list_conda_envs().items():
            try:
                pkgs = self._get_packages(env_path, found_targets)
            except Exception:
                continue
            if all(pkg in pkgs for pkg in found_targets):
                selected_env_pkgs = pkgs
                break

        if selected_env_pkgs:
            for pkg in found_targets:
                if results.get(pkg) is None and pkg in selected_env_pkgs:
                    results[pkg] = selected_env_pkgs[pkg]

        return results

    def _list_conda_envs(self) -> dict[str, str]:
        if self._envs is None:
            result = subprocess.run(
                ["conda", "env", "list", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            envs_info = json.loads(result.stdout)
            self._envs = {path.split("/")[-1]: path for path in envs_info["envs"]}
        return self._envs

    def _get_packages(self, env_path: str, targets: set[str]) -> dict[str, str]:
        if env_path not in self._packages_by_env:
            result = subprocess.run(
                ["conda", "list", "--prefix", env_path, "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            all_packages = json.loads(result.stdout)
            self._packages_by_env[env_path] = {
                pkg["name"]: pkg["version"] for pkg in all_packages
            }
        return {
            pkg_name: version
            for pkg_name, version in self._packages_by_env[env_path].items()
            if pkg_name.lower() in targets
        }


class ProvenanceBuilder:
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
        with open(self.provenance_filename, "w", encoding="utf8") as f:
            json.dump(provenance.jsonld, f, indent=4, ensure_ascii=False)

        Graph().parse(data=provenance.jsonld, format="json-ld").serialize(
            self.provenance_ttl_filename, format="ttl"
        )

    def create_external_directory(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def workspace(self) -> Iterator[None]:
        self.create_external_directory()
        try:
            yield
        finally:
            self.clean_data()

    def clean_data(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)

        for file_name in (self.provenance_filename, self.provenance_ttl_filename):
            if Path(file_name).exists():
                os.remove(file_name)

    def _create_processing_step_node(
        self, job, file_nodes: JsonLdNodeMap
    ) -> JsonLdNode:
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

    def _job_input_files(self, job) -> list[str]:
        return [
            file_path
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
            for file_path in dag_job.input
        ]

    def _job_conda_files(self, job) -> list[Any]:
        return [
            dag_job.conda_env
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
        ]

    def _job_shell_commands(self, job) -> list[str]:
        return [
            dag_job.shellcmd
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid and dag_job.shellcmd
        ]

    def _add_shell_supplemental_files(self, job) -> None:
        for shell_cmd in self._job_shell_commands(job):
            script_file, _ = self._extract_script_and_files(shell_cmd)
            if not script_file:
                continue
            resolved_shell_path = self._copy_external_relative_files(script_file)
            self._add_supplemental_file(
                resolved_shell_path,
                resolved_shell_path,
                get_mime_type(resolved_shell_path),
            )

    def _method_optional_fields(self, job) -> JsonLdNode:
        optional_fields: JsonLdNode = {}
        tools = self._job_tools(job)
        if tools:
            optional_fields["implemented by"] = [
                {"@id": tool["@id"]} for tool in tools
            ]
        return optional_fields

    def _job_tools(self, job) -> list[JsonLdNode]:
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

    def _populate_processing_step_files(
        self,
        job,
        node: JsonLdNode,
        file_nodes: JsonLdNodeMap,
        optional_fields: JsonLdNode,
    ) -> None:
        for file_path, source in [(f, "input") for f in self._job_input_files(job)] + [
            (f, "output") for f in job.output
        ]:
            if not self._is_file(file_path):
                continue
            file_node = self._add_file(file_path, file_nodes)
            node_key = "has input" if source == "input" else "has output"
            node[node_key].append({"@id": file_node["@id"]})
            self._merge_parameter_metadata(
                optional_fields,
                self._extract_parameters(job.rule, file_path, file_node).get(job.rule, {}),
            )

    def _merge_parameter_metadata(
        self, optional_fields: JsonLdNode, rule_data: JsonLdNode
    ) -> None:
        for key in ("has parameter", "investigates"):
            if key in rule_data:
                optional_fields.setdefault(key, []).append(rule_data[key])

    def _create_method_node(self, job, optional_fields: JsonLdNode) -> str:
        method_id = f"local:method_{job.rule}_{job.job.jobid}"
        self.state.methods[method_id] = {
            "@id": method_id,
            "@type": "method",
            "label": f"{job.rule}_{job.job.jobid}",
            **optional_fields,
        }
        return method_id

    def _add_snakefile_supplemental_file(self) -> None:
        snakefile = self._find_snakefile()
        if not snakefile:
            return
        snakefile_name, snakepath = snakefile
        self._add_supplemental_file(
            snakefile_name,
            snakepath,
            "text/x-python",
        )

    def _add_file(self, file_path: str, file_dict: JsonLdNodeMap) -> JsonLdNode:
        resolved_path = self._copy_external_relative_files(file_path)
        if resolved_path not in file_dict:
            file_dict[resolved_path] = {
                "@id": f"local:file_{len(file_dict)}",
                "@type": "cr:FileObject",
                "label": resolved_path,
            }
        return file_dict[resolved_path]

    def _add_supplemental_file(
        self, source_path: str, dest_path: str, encoding_format: str
    ) -> None:
        self.state.supplemental_files[dest_path] = CrateFile(
            source_path=source_path,
            dest_path=dest_path,
            name=source_path,
            encoding_format=encoding_format,
        )

    def _add_research_problem(self) -> None:
        if "researchProblem" in self.config_data:
            self.state.research_problem_id = "local:research_problem"
            research_problem = {
                "@id": self.state.research_problem_id,
                "@type": "mardi4nfdi:ResearchProblem",
            }
            for key, value in self.config_data["researchProblem"].items():
                property_key = f"{key.replace(' ', '_').lower()}"
                research_problem[property_key] = value
            self.state.research_problem[self.state.research_problem_id] = research_problem

    def _add_benchmark_processing_step(self, sorted_jobs) -> None:
        self.state.benchmark_processing_step_id = "local:processing_step_benchmark"
        earliest_start = min(item.starttime for item in sorted_jobs)
        latest_end = max(item.endtime for item in sorted_jobs)
        benchmark_node = {
            "@id": self.state.benchmark_processing_step_id,
            "@type": "processing step",
            "label": "benchmark",
            "start time": self._get_time_str(earliest_start),
            "end time": self._get_time_str(latest_end),
            "has input": [],
            "has output": [],
            "has parameter": [],
            "investigates": (
                {"@id": self.state.research_problem_id}
                if self.state.research_problem_id
                else []
            ),
        }
        self.state.processing_steps[self.state.benchmark_processing_step_id] = benchmark_node

    def _extract_parameters(
        self, rule: str, file_path: str, file_node: JsonLdNode
    ) -> JsonLdNodeMap:
        metadata: JsonLdNodeMap = {}
        params = self.parameter_extractor.extract(rule, file_path)
        for processing_step_name, processing_step_data in params.items():
            metadata.setdefault(processing_step_name, {})
            for parameter_type in ["has parameter", "investigates"]:
                if parameter_type not in processing_step_data:
                    continue
                metadata[processing_step_name].setdefault(parameter_type, [])
                for entry in processing_step_data[parameter_type]:
                    for name, data in entry.items():
                        sanitized_name = name.replace("-", "_")
                        param_node = self._build_parameter_node(name, data)
                        param_id = self._intern_parameter_node(
                            sanitized_name, param_node
                        )
                        metadata[processing_step_name][parameter_type].append(
                            {"@id": param_id}
                        )
                        self._add_unique_field(
                            sanitized_name, param_id, file_node, data
                        )
        return metadata

    def _build_parameter_node(self, name: str, data: JsonLdNode) -> JsonLdNode:
        param_node: JsonLdNode = {
            "@type": (
                "text variable"
                if data["data-type"] == "schema:Text"
                else "numerical variable"
            ),
            "label": name,
        }
        if data["data-type"] == "schema:Text":
            param_node["has string value"] = data["value"]
        else:
            param_node["has numerical value"] = data["value"]
        unit_ref = self._resolve_unit_reference(data.get("unit"))
        if unit_ref:
            param_node["has unit"] = {"@id": unit_ref}
        return param_node

    def _resolve_unit_reference(self, unit: str | None) -> str | None:
        if not unit:
            return None
        if unit not in self.state.qudt_mapping:
            resolved_unit = self.resources.get_qudt_unit(unit)
            self.state.qudt_mapping[unit] = resolved_unit or unit
        return self.state.qudt_mapping[unit]

    def _intern_parameter_node(
        self, sanitized_name: str, param_node: JsonLdNode
    ) -> str:
        for key, value in self.state.parameters.items():
            if value == param_node:
                return key
        param_id = f"local:variable_{sanitized_name}_{self.state.param_counter}"
        self.state.parameters[param_id] = param_node
        self.state.param_counter += 1
        return param_id

    def _add_tools(self, env_file_content: str) -> list:
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

    def _add_unique_field(self, name, param_id, file_node, data):
        unique_key = (
            name,
            param_id,
            file_node.get("@id") if isinstance(file_node, dict) else file_node,
            data.get("data-type"),
        )

        if unique_key in self.state.unique_fields:
            return

        new_field = {
            "@type": "Field",
            "represents": {"@id": param_id},
            "source": {"@id": f"local:source_{name}_{self.state.field_counter}"},
            **(
                {"dataType": {"@id": data["data-type"]}}
                if data.get("data-type")
                else {}
            ),
        }

        new_source = {
            "@id": f"local:source_{name}_{self.state.field_counter}",
            "@type": "cr:DataSource",
            "file object": {"@id": file_node["@id"]},
            "extract": {
                "@id": f"local:extract_{name}_{self.state.field_counter}"
            },
        }

        new_extract = {
            "@id": f"local:extract_{name}_{self.state.field_counter}",
            "@type": "cr:DataSource",
            "jsonPath": data["json-path"],
        }

        key = f"{name}_{self.state.field_counter}"
        self.state.fields[key] = {
            "@id": f"local:field_{name}_{self.state.field_counter}",
            **new_field,
        }
        self.state.extracts[key] = new_extract
        self.state.sources[key] = new_source
        self.state.unique_fields.add(unique_key)
        self.state.field_counter += 1

    def _extract_script_and_files(
        self, cmd: str
    ) -> tuple[Optional[str], list[str]]:
        interpreters = {
            "python",
            "python3",
            "python2",
            "pypy",
            "pypy3",
            "ruby",
            "perl",
            "node",
            "deno",
            "php",
            "lua",
            "Rscript",
            "R",
            "bash",
            "sh",
            "zsh",
            "ksh",
            "fish",
        }

        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            return None, []

        if not tokens:
            return None, []

        script_path = None
        file_paths = []

        if Path(tokens[0]).name in interpreters:
            for i, tok in enumerate(tokens[1:], start=1):
                if tok.startswith("-"):
                    continue
                script_path = tok
                break
            start_idx = i + 1 if script_path else 1
        else:
            first = Path(tokens[0])
            if first.suffix and first.suffix not in {".exe", ".bat", ".cmd"}:
                script_path = str(first)
            start_idx = 1

        for tok in tokens[start_idx:]:
            if tok.startswith("-") or tok in {">", "2>&1"} or tok.isnumeric():
                continue
            if Path(tok).suffix or "/" in tok or tok.startswith(".."):
                file_paths.append(tok)

        return script_path, file_paths

    def _find_snakefile(self):
        current_dir = os.getcwd()
        for file in os.listdir(current_dir):
            if file.lower() == "snakefile":
                rel_path = os.path.relpath(os.path.join(current_dir, file))
                return file, rel_path
        return None

    def _add_precedes_relations(self, jsonld_data: dict) -> dict:
        g = Graph()
        g.parse(data=json.dumps(jsonld_data), format="json-ld")
        schema = Namespace("https://schema.org/")
        new_relations = []
        for a, _, f1 in g.triples((None, schema.result, None)):
            for b, _, f2 in g.triples((None, schema.object, None)):
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

    def _is_file(self, file_name: str) -> bool:
        return os.path.isfile(file_name)

    def _random_hash_from_json(self, json_content: dict, length=8) -> str:
        json_str = json.dumps(json_content, sort_keys=True).encode("utf-8")
        hash_value = hashlib.sha256(json_str).hexdigest()
        return hash_value[:length]

    def _copy_external_relative_files(self, path_str) -> str:
        original_path = Path(path_str).resolve()
        current_dir = Path.cwd().resolve()

        try:
            _ = original_path.relative_to(current_dir)
            return str(path_str)
        except ValueError:
            pass

        common_root = os.path.commonpath([str(current_dir), str(original_path)])
        relative_structure = Path(original_path).relative_to(common_root)
        target_path = Path(self.external_directory_name) / relative_structure

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original_path, target_path)

        return str(target_path)

    def _get_time_str(self, timestamp) -> str:
        try:
            return f"{datetime.fromtimestamp(timestamp)}"
        except Exception:
            return ""
