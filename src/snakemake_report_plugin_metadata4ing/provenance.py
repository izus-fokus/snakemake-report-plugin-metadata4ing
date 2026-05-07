import hashlib
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml
from pint import UnitRegistry
from rdflib import Graph, Namespace

from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)
from snakemake_report_plugin_metadata4ing.models import CrateFile, ProvenanceResult
from snakemake_report_plugin_metadata4ing.utils import get_mime_type


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

        self.context_data = {}
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
        self.benchmark_processing_step_id = ""
        self.research_problem_id = ""
        self.simulation_hash = ""
        self.unit_graph = Graph()
        self.qudt_mapping_dict = {}
        self.qudt_url = "http://qudt.org/schema/qudt/"
        self.unit_url = "http://qudt.org/vocab/unit/"
        self.mardi4nfdi_url = "https://mardi4nfdi.de/mathmoddb#"
        self.QUDT_NS = Namespace(self.qudt_url)
        self.UNIT_NS = Namespace(self.unit_url)
        self.ureg = UnitRegistry()
        self.supplemental_files = {}

    def build(self) -> ProvenanceResult:
        self._get_context()
        self._get_qudt()

        jsonld = {
            "@context": self.context_data.get("@context", {}),
            "@graph": [],
        }
        jsonld["@context"]["unit"] = self.unit_url
        jsonld["@context"]["mardi4nfdi"] = self.mardi4nfdi_url

        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        file_nodes = {}
        file_counter = 0

        self._add_research_problem()
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

        for graph_fragment in (
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
            jsonld["@graph"].extend(graph_fragment.values())

        self.simulation_hash = self._random_hash_from_json(jsonld, 16)
        jsonld["@context"][
            "local"
        ] = f"https://local-domain.org/{self.simulation_hash}/"
        jsonld = self._add_precedes_relations(jsonld)

        return ProvenanceResult(
            jsonld=jsonld,
            context_data=self.context_data,
            file_nodes=file_nodes,
            processing_steps=self.processing_steps,
            parameters=self.param_dict,
            methods=self.methods,
            tools=self.tools_dict,
            fields=self.field_dict,
            sources=self.source_dict,
            extracts=self.extract_dict,
            research_problem=self.research_problem,
            supplemental_files=list(self.supplemental_files.values()),
            simulation_hash=self.simulation_hash,
            benchmark_processing_step_id=self.benchmark_processing_step_id,
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

    def clean_data(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)

        for file_name in (self.provenance_filename, self.provenance_ttl_filename):
            if Path(file_name).exists():
                os.remove(file_name)

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
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
            for f in dag_job.input
        ]

        conda_files = [
            dag_job.conda_env
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid
        ]

        shell_cmds = [
            dag_job.shellcmd
            for dag_job in self.dag.jobs
            if dag_job.jobid == job.job.jobid and dag_job.shellcmd
        ]

        for shell_cmd_file in shell_cmds:
            script_file, _ = self._extract_script_and_files(shell_cmd_file)
            if script_file:
                resolved_shell_path = self._copy_external_relative_files(script_file)
                self._add_supplemental_file(
                    resolved_shell_path,
                    resolved_shell_path,
                    get_mime_type(resolved_shell_path),
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
                metadata = self._extract_parameters(job.rule, file, file_node)
                rule_data = metadata.get(job.rule, {})
                for key in ("has parameter", "investigates"):
                    if key in rule_data:
                        optional_fields.setdefault(key, []).append(rule_data[key])

        self.methods[new_method_node_id] = {
            "@id": new_method_node_id,
            "@type": "method",
            "label": f"{job.rule}_{job.job.jobid}",
            **optional_fields,
        }
        node["realizes method"] = {"@id": new_method_node_id}

        snakefile = self._find_snakefile()
        if snakefile:
            snakefile_name, snakepath = snakefile
            self._add_supplemental_file(
                snakefile_name,
                snakepath,
                "text/x-python",
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

    def _add_supplemental_file(
        self, source_path: str, dest_path: str, encoding_format: str
    ) -> None:
        self.supplemental_files[dest_path] = CrateFile(
            source_path=source_path,
            dest_path=dest_path,
            name=source_path,
            encoding_format=encoding_format,
        )

    def _add_research_problem(self):
        if "researchProblem" in self.config_data:
            self.research_problem_id = "local:research_problem"
            research_problem = {
                "@id": self.research_problem_id,
                "@type": "mardi4nfdi:ResearchProblem",
            }
            for key, value in self.config_data["researchProblem"].items():
                property_key = f"{key.replace(' ', '_').lower()}"
                research_problem[property_key] = value
            self.research_problem[self.research_problem_id] = research_problem

    def _add_benchmark_processing_step(self, sorted_jobs):
        self.benchmark_processing_step_id = "local:processing_step_benchmark"
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
        self.processing_steps[self.benchmark_processing_step_id] = benchmark_node

    def _extract_parameters(self, rule, file, file_node):
        metadata = {}
        extract_params_obj = self._load_param_extractor_obj()
        params = extract_params_obj.extract_params(rule, file)
        if params:
            params = self._validate_extract_param_output(params)
            for processing_step_name, processing_step_data in params.items():
                metadata.setdefault(processing_step_name, {})
                for parameter_type in ["has parameter", "investigates"]:
                    if parameter_type in processing_step_data:
                        metadata[processing_step_name].setdefault(
                            parameter_type, []
                        )
                        for entry in processing_step_data[parameter_type]:
                            for name, data in entry.items():
                                sanitized_name = name.replace("-", "_")
                                param_id = ""
                                param = {
                                    "@type": (
                                        "text variable"
                                        if data["data-type"] == "schema:Text"
                                        else "numerical variable"
                                    ),
                                    "label": name,
                                }
                                if data["data-type"] == "schema:Text":
                                    param["has string value"] = data["value"]
                                else:
                                    param["has numerical value"] = data["value"]

                                if data["unit"]:
                                    if data["unit"] in self.qudt_mapping_dict:
                                        param["has unit"] = {
                                            "@id": self.qudt_mapping_dict[
                                                data["unit"]
                                            ]
                                        }
                                    else:
                                        qudt_unit = self._get_qudt_unit_from_mapping(
                                            data["unit"]
                                        )
                                        self.qudt_mapping_dict[
                                            data["unit"]
                                        ] = qudt_unit
                                        if qudt_unit:
                                            param["has unit"] = {
                                                "@id": qudt_unit
                                            }
                                        else:
                                            self.qudt_mapping_dict[
                                                data["unit"]
                                            ] = data["unit"]
                                            param["has unit"] = {
                                                "@id": data["unit"]
                                            }

                                if param in self.param_dict.values():
                                    param_id = next(
                                        (
                                            key
                                            for key, value in self.param_dict.items()
                                            if value == param
                                        ),
                                        None,
                                    )
                                else:
                                    param_id = (
                                        f"local:variable_{sanitized_name}_"
                                        f"{self.param_counter}"
                                    )
                                    self.param_dict[param_id] = param
                                    self.param_counter += 1
                                metadata[processing_step_name][
                                    parameter_type
                                ].append({"@id": param_id})
                                self._add_unique_field(
                                    sanitized_name, param_id, file_node, data
                                )
        return metadata

    def _extract_tools_from_yaml(self, env_file_content: str) -> dict:
        results = {}
        found_targets = set()
        parsed = yaml.safe_load(env_file_content)
        dependencies = parsed.get("dependencies", [])

        version_pattern = re.compile(r"([a-zA-Z0-9_.\-]+)([=><!~]+.*)?")

        for dep in dependencies:
            if isinstance(dep, str):
                match = version_pattern.match(dep.strip())
                if match:
                    pkg_name = match.group(1).lower()
                    version = (
                        match.group(2).lstrip("=") if match.group(2) else None
                    )
                    results[pkg_name] = version
                    found_targets.add(pkg_name)
            elif isinstance(dep, dict):
                for _, pkgs in dep.items():
                    for pkg in pkgs:
                        match = version_pattern.match(pkg.strip())
                        if match:
                            pkg_name = match.group(1).lower()
                            version = (
                                match.group(2).lstrip("=")
                                if match.group(2)
                                else None
                            )
                            results[pkg_name] = version
                            found_targets.add(pkg_name)

        envs = self._list_conda_envs()

        selected_env_pkgs = None
        for _, env_path in envs.items():
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

    def _add_tools(self, env_file_content: str) -> list:
        tools_list = []
        tools = self._extract_tools_from_yaml(env_file_content)
        if tools:
            for name, version in tools.items():
                if name not in self.tools_dict:
                    item = {
                        "@id": f"local:tool_{self.tool_counter}",
                        "@type": "schema:SoftwareApplication",
                        "label": name,
                        **({"softwareVersion": version} if version else {}),
                    }
                    self.tools_dict[name] = item
                    self.tool_counter += 1
                    tools_list.append(item)
                else:
                    tools_list.append(self.tools_dict[name])
        return tools_list

    def _list_conda_envs(self):
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        envs_info = json.loads(result.stdout)
        return {path.split("/")[-1]: path for path in envs_info["envs"]}

    def _get_packages(self, env_path, targets):
        result = subprocess.run(
            ["conda", "list", "--prefix", env_path, "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        all_packages = json.loads(result.stdout)
        return {
            pkg["name"]: pkg["version"]
            for pkg in all_packages
            if pkg["name"].lower() in targets
        }

    def _get_context(self):
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("metadata4ing.jsonld").open("r", encoding="utf-8") as f:
            self.context_data = json.load(f)

    def _get_qudt(self):
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("qudt.ttl").open("r", encoding="utf-8") as f:
            qudt_data = f.read()
            self.unit_graph.parse(data=qudt_data, format="ttl")

    def _get_qudt_unit_from_mapping(self, unit: str) -> str | None:
        with resources.files(
            "snakemake_report_plugin_metadata4ing.ontologies"
        ).joinpath("qudt-mapping.json").open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        pint_unit = self.ureg.parse_units(unit)
        if str(pint_unit) in mapping:
            return f"unit:{mapping[str(pint_unit)]}"
        return unit

    def _load_param_extractor_obj(self):
        script_path = Path(self.settings.paramscript).expanduser().resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        module_path = str(script_path)

        spec = importlib.util.spec_from_file_location(
            "extractor_module", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        extractor_class = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ParameterExtractorInterface)
                and obj is not ParameterExtractorInterface
            ):
                extractor_class = obj
                break

        if extractor_class is None:
            raise ImportError(
                "No subclass of ParameterExtractorInterface found in script"
            )

        return extractor_class()

    def _add_unique_field(self, name, param_id, file_node, data):
        unique_key = (
            name,
            param_id,
            file_node.get("@id") if isinstance(file_node, dict) else file_node,
            data.get("data-type"),
        )

        if unique_key in self._unique_fields:
            return

        new_field = {
            "@type": "Field",
            "represents": {"@id": param_id},
            "source": {"@id": f"local:source_{name}_{self.field_counter}"},
            **(
                {"dataType": {"@id": data["data-type"]}}
                if data.get("data-type")
                else {}
            ),
        }

        new_source = {
            "@id": f"local:source_{name}_{self.field_counter}",
            "@type": "cr:DataSource",
            "file object": {"@id": file_node["@id"]},
            "extract": {"@id": f"local:extract_{name}_{self.field_counter}"},
        }

        new_extract = {
            "@id": f"local:extract_{name}_{self.field_counter}",
            "@type": "cr:DataSource",
            "jsonPath": data["json-path"],
        }

        key = f"{name}_{self.field_counter}"
        self.field_dict[key] = {
            "@id": f"local:field_{name}_{self.field_counter}",
            **new_field,
        }
        self.extract_dict[key] = new_extract
        self.source_dict[key] = new_source
        self._unique_fields.add(unique_key)
        self.field_counter += 1

    def _validate_extract_param_output(self, result):
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
            for rk in required_keys:
                if rk not in entry_value:
                    raise ValueError(
                        f"Missing key '{rk}' in value for '{entry_key}'."
                    )

            if entry_value["unit"] and not isinstance(entry_value["unit"], str):
                raise TypeError(f"'unit' for '{entry_key}' must be a string.")
            if not isinstance(entry_value["json-path"], str):
                raise TypeError(
                    f"'json-path' for '{entry_key}' must be a string."
                )
            if not isinstance(entry_value["data-type"], str):
                raise TypeError(
                    f"'data-type' for '{entry_key}' must be a string."
                )

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
