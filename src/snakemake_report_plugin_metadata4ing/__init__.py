from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph, Namespace
import json
import importlib.util
import inspect
from snakemake_report_plugin_metadata4ing.interfaces import (
    ParameterExtractorInterface,
)
from rocrate.rocrate import ROCrate
import mimetypes
import shlex
import os
import hashlib
import shutil
import yaml
import subprocess
import re
from importlib import resources
from pint import UnitRegistry


@dataclass
class ReportSettings(ReportSettingsBase):
    paramscript: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Path to external Python script which implements the ParameterExtractorInterface.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )
    
    config: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Config file in JSON format containing metadata about the research problem.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )

    filename: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Name of the file to be created for storing provenance.",
            "env_var": False,
            "required": False,
            "parse_func": Path,
            "unparse_func": str,
        },
    )


class Reporter(ReporterBase):
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
        self.tool_counter = 0
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
        self.metadata4ing_url = "http://w3id.org/nfdi4ing/metadata4ing#"
        self.obo_url = "http://purl.obolibrary.org/obo/"
        self.QUDT_NS = Namespace(self.qudt_url)
        self.UNIT_NS = Namespace(self.unit_url)
        self.ontologies_path = (
            resources.files("snakemake_report_plugin_metadata4ing")
            / "ontologies"
        )
        self.ureg = UnitRegistry()
        
        if self.settings.filename:
            self._validate_filename(str(self.settings.filename))
        
        self._extend_rocrate_context()
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
        
        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        file_nodes = {}
        file_counter = 0

        self._add_research_problem()
        self._add_rocrate_config_data()
        self._add_benchmark_processing_step(sorted_jobs)
        
        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_processing_step_node(job, file_nodes, file_counter)
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
        
        self._add_provenance_nodes_to_crate(jsonld["@graph"])
        self._create_ttl_from_jsonld(jsonld)
        self._add_ro_crate_file_nodes(file_nodes)
        self._create_ro_crate_file()
        self._clean_data()

    def _read_config(self):
        if not self.settings.config:
            return None

        config_path = Path(self.settings.config).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            try:
                self.config_data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Error parsing JSON config file: {e}"
                ) from e
    
    def _extend_rocrate_context(self):
        self.crate.metadata.extra_terms['m4i'] = self.metadata4ing_url
        self.crate.metadata.extra_terms['obo'] = self.obo_url
        self.crate.metadata.extra_terms['unit'] = self.unit_url
        self.crate.metadata.extra_terms['mardi4nfdi'] = self.mardi4nfdi_url
            
    def _add_rocrate_config_data(self):
        rocrate_info = self.config_data.get("rocrate", {})
        self.crate.name = rocrate_info.get("name")
        self.crate.description = rocrate_info.get("description")
        self.crate.license = rocrate_info.get("license")

    def _create_processing_step_node(self, job, files_dict, file_counter):
        node = {
            "@id": f"#processing_step_{job.job.jobid}",
            "@type": "Action",
            "rdfs:label": f"{job.rule}_{job.job.jobid}",
            "schema:startTime": self._get_time_str(job.starttime),
            "schema:endTime": self._get_time_str(job.endtime),
            "schema:object": [],
            "schema:result": [],
            "m4i:realizesMethod": [],
            "schema:isPartOf": {
                "@id": self.benchmark_processing_step_id
            }
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

        tools = {}
        for conda_file in conda_files:
            if conda_file:
                if conda_file in self.conda_tools_cache:
                    tools = self.conda_tools_cache[conda_file]
                else:
                    tools = self._add_tools(conda_file.content)
                    self.conda_tools_cache[conda_file] = tools

        for file, source in [(f, 'input') for f in input_files] + [(f, 'output') for f in job.output]:
            if not self._is_file(file):
                continue
            file_node, file_counter = self._add_file(
                file, files_dict, file_counter
            )
            if source == 'input':
                node["schema:object"].append({"@id": file_node["@id"]})
            else:
                node["schema:result"].append({"@id": file_node["@id"]})
            if self.settings.paramscript:
                metadata = self._extract_parameters(job.rule, file, file_node)
                if job.rule in metadata:
                    for param_type in ["has parameter", "investigates"]:
                        if param_type in metadata[job.rule]:
                            new_method_node_id = (f"#method_{job.rule}_{job.job.jobid}")
                            rule_data = metadata.get(job.rule, {})
                            mapping = {
                                "has parameter": "m4i:hasParameter", 
                                "investigates": "m4i:investigates"
                            }
                            optional_fields = {mapping[k]: [rule_data[k]] for k in ("has parameter", "investigates") if k in rule_data}
                            if tools:
                                optional_fields["m4i:implementedByTool"] = [{"@id": tool["@id"]} for tool in tools]
                            self.methods[new_method_node_id] = {
                                "@id": new_method_node_id,
                                "@type": "m4i:Method",
                                "rdfs:label": f"{job.rule}_{job.job.jobid}",
                                **optional_fields
                            }
                            node["m4i:realizesMethod"] = {"@id": new_method_node_id}
                else:
                    for key, _ in metadata.items():
                        new_method_node_id = (f"#method_{job.job.jobid}_{key}")
                        new_child_node_id = (
                            f"#processing_step_{job.job.jobid}_{key}"
                        )
                        self.methods[new_method_node_id] = {
                            "@id": new_method_node_id,
                            "@type": "m4i:Method",
                            "rdfs:label": f"{job.rule}_{job.job.jobid}_{key}",
                            "m4i:hasParameter": [metadata[key]["has parameter"]],
                            "m4i:investigates": [metadata[key]["investigates"]],
                        }
                        self.child_nodes[new_child_node_id] = {
                            "@id": new_child_node_id,
                            "@type": "Action",
                            "rdfs:label": f"{job.rule}_{job.job.jobid}_{key}",
                            "schema:startTime": self._get_time_str(job.starttime),
                            "schema:endTime": self._get_time_str(job.endtime),
                            "m4i:realizesMethod": {"@id": new_method_node_id},
                            "schema:object": [],
                            "schema:result": [],
                            "schema:isPartOf": {
                                "@id": f"#processing_step_{job.job.jobid}"
                            },
                        }

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
                "@id": resolved_path,
                "@type": "cr:FileObject",
                "rdfs:label": resolved_path,
            }
            counter += 1
        return file_dict[resolved_path], counter

    def _add_research_problem(self):
        if "researchProblem" in self.config_data:
            self.research_problem_id = f"#research_problem"
            research_problem = {
                "@id": self.research_problem_id,
                "@type": "mardi4nfdi:ResearchProblem"
            }
            for key, value in self.config_data["researchProblem"].items():
                property_key = f"{key.replace(' ', '_').lower()}"
                research_problem[property_key] = value
            self.research_problem[self.research_problem_id] = research_problem
            
    def _add_benchmark_processing_step(self, sorted_jobs):
        self.benchmark_processing_step_id = f"#processing_step_benchmark"
        self.crate.mainEntity = {"@id": self.benchmark_processing_step_id}
        earliest_start = min(item.starttime for item in sorted_jobs)
        latest_end = max(item.endtime for item in sorted_jobs)
        benchmark_node = {
            "@id": self.benchmark_processing_step_id,
            "@type": "Action",
            "rdfs:label": "benchmark",
            "schema:startTime": self._get_time_str(earliest_start),
            "schema:endTime": self._get_time_str(latest_end),
            "schema:object": [],
            "schema:result": [],
            "m4i:hasParameter": [],
            "m4i:investigates": {"@id": self.research_problem_id} if self.research_problem_id else []
        }
        self.processing_steps[id] = benchmark_node
        
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
                                name = name.replace("-", "_")
                                param_id = ""
                                param = {
                                    "@type": (
                                        "text variable"
                                        if data["data-type"] == "schema:Text"
                                        else "schema:PropertyValue"
                                    ),
                                    "rdfs:label": name,
                                }
                                if data["data-type"] == "schema:Text":
                                    param["schema:value"] = data["value"]
                                else:
                                    param["schema:value"] = data["value"]
                                    if data["unit"]:
                                        if (
                                            data["unit"]
                                            in self.qudt_mapping_dict
                                        ):
                                            param["schema:unitCode"] = {
                                                "@id": self.qudt_mapping_dict[
                                                    data["unit"]
                                                ]
                                            }
                                        else:
                                            qudt_unit = (
                                                self._get_qudt_unit_from_mapping(
                                                    data["unit"]
                                                )
                                            )
                                            self.qudt_mapping_dict[
                                                data["unit"]
                                            ] = qudt_unit
                                            if qudt_unit:
                                                param["schema:unitCode"] = {
                                                    "@id": qudt_unit
                                                }
                                            else:
                                                self.qudt_mapping_dict[
                                                    data["unit"]
                                                ] = data["unit"]
                                                param["schema:unitCode"] = {
                                                    "@id": data["unit"]
                                                }

                                if param in self.param_dict.values():
                                    param_id = next(
                                        (
                                            k
                                            for k, v in self.param_dict.items()
                                            if v == param
                                        ),
                                        None,
                                    )
                                else:
                                    param_id = f"#variable_{name}_{self.param_counter}"
                                    self.param_dict[param_id] = param
                                    self.param_counter += 1
                                metadata[processing_step_name][
                                    parameter_type
                                ].append({"@id": param_id})
                                self._add_unique_field(
                                    name, param_id, file_node, data
                                )
        return metadata

    def _extract_tools_from_yaml(self, env_file_content: str) -> dict:
        results = {}
        found_targets = set()
        parsed = yaml.safe_load(env_file_content)
        dependencies = parsed.get("dependencies", [])

        version_pattern = re.compile(r"([a-zA-Z0-9_.\-]+)([=><!~]+.*)?")

        # Parse YAML dependencies
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

        # Find the first env that contains all target packages
        selected_env_pkgs = None
        for _, env_path in envs.items():
            try:
                pkgs = self._get_packages(env_path, found_targets)
            except Exception:
                continue

            if all(pkg in pkgs for pkg in found_targets):
                selected_env_pkgs = pkgs
                break  # Stop at the first matching environment

        # Fill in missing versions from the selected environment
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
                        "@id": f"#tool_{self.tool_counter}",
                        "@type": "schema:SoftwareApplication",
                        "rdfs:label": name,
                        **(
                            {"schema:softwareVersion": version}
                            if version
                            else {}
                        ),
                    }
                    self.tools_dict[name] = item
                    self.tool_counter += 1
                    tools_list.append(item)
                else:
                    tools_list.append(self.tools_dict[name])
        return tools_list

    def _list_conda_envs(self):
        """Return a dict {env_name: env_path} of all conda environments."""
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        envs_info = json.loads(result.stdout)
        return {path.split("/")[-1]: path for path in envs_info["envs"]}

    def _get_packages(self, env_path, targets):
        """Return dict {package: version} for given env path."""
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

    def _add_ro_crate_file_nodes(self, file_nodes):
        _ = self.crate.add_file(
            self.provenance_filename,
            dest_path=self.provenance_filename,
            properties={
                "name": self.provenance_filename,
                "encodingFormat": "application/ld+json",
                "conformsTo": [
                    "https://w3id.org/ro/crate/1.1",
                    "https://w3id.org/nfdi4ing/metadata4ing/1.3.1",
                ],
            },
        )

        _ = self.crate.add_file(
            self.provenance_ttl_filename,
            dest_path=self.provenance_ttl_filename,
            properties={
                "name": self.provenance_ttl_filename,
                "encodingFormat": "text/turtle",
            },
        )

        for file in file_nodes.keys():
            _ = self.crate.add_file(
                file,
                dest_path=file,
                properties={
                    "name": file,
                    "encodingFormat": self._get_mime_type(file),
                },
            )

    def _create_ttl_from_jsonld(self, data: dict):
        Graph().parse(data=data, format="json-ld").serialize(
            "provenance.ttl", format="ttl"
        )

    def _create_ro_crate_file(self):
        if self.settings.filename:
            self.crate.write_zip(f"{self.settings.filename}.zip")
        else:
            self.crate.write_zip(
                f"ro-crate-metadata-{self.simulation_hash}.zip"
            )

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
        new_field = {
            "@type": "Field",
            "represents": {"@id": param_id},
            "source": {
                "file object": {"@id": file_node["@id"]},
                "cr:extract": {"cr:jsonPath": data["json-path"]},
            },
            **(
                {"cr:dataType": data["data-type"]}
                if data.get("data-type")
                else {}
            ),
        }

        for existing in self.field_dict.values():
            existing_no_id = {k: v for k, v in existing.items() if k != "@id"}
            if existing_no_id == new_field:
                return

        key = f"{name}_{self.field_counter}"
        self.field_dict[key] = {
            "@id": f"#field_{name}_{self.field_counter}",
            **new_field,
        }
        self.field_counter += 1

    def _validate_extract_param_output(self, result):
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")

        def _validate_entry(entry_key, entry_value):
            """Validate the innermost dictionary with value/unit/json-path/data-type."""
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
            """Validate a section like 'parameters' or 'investigates'."""
            if not isinstance(section_content, list):
                raise TypeError(f"'{section_name}' must be a list.")
            for idx, item in enumerate(section_content):
                if not isinstance(item, dict):
                    raise TypeError(
                        f"Each item in '{section_name}' must be a dictionary."
                    )
                if len(item) != 1:
                    raise ValueError(
                        f"Each item in '{section_name}' must have exactly one key, found {len(item)}."
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
                k in root_value for k in ["has parameter", "investigates"]
            ):
                raise ValueError(
                    f"Root key '{root_key}' must contain at least 'has parameter' or 'investigates'."
                )

            for section in ["has parameter", "investigates"]:
                if section in root_value:
                    _validate_section(section, root_value[section])

        return result

    def _get_mime_type(self, file_name: str) -> str:
        file_name = Path(file_name).name
        mime_type, _ = mimetypes.guess_type(file_name, strict=False)
        return mime_type or "application/octet-stream"

    def _extract_script_and_files(
        self, cmd: str
    ) -> tuple[Optional[str], list[str]]:
        _INTERPRETERS = {
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

        if Path(tokens[0]).name in _INTERPRETERS:
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
                return (file, rel_path)
        return None

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
            key = "obo:BFO_0000063"
            existing = source_node.get(key)
            new_link = {"@id": f"#{target_id}"}
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
        if local.startswith("#"):
            local = local.replace("#", "")
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

    def _create_external_directory(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    def _get_time_str(self, timestamp) -> str:
        try:
            return f"{datetime.fromtimestamp(timestamp)}"
        except Exception:
            return ""

    def _clean_data(self):
        target_dir = Path(self.external_directory_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        os.remove(self.provenance_filename)
        os.remove(self.provenance_ttl_filename)

    def _add_provenance_nodes_to_crate(self, nodes: list[dict]) -> None:
        for node in nodes:
            if node.get("@type", "").startswith("Field"):
                continue
            self.crate.add_jsonld(node)
            
    def _validate_filename(self, filename: str) -> None:
        if not filename or filename.strip() == "":
            raise ValueError("Filename cannot be empty.")

        illegal_pattern = r'[<>:"/\\|?*]'
        if re.search(illegal_pattern, filename):
            raise ValueError(
                f"Filename '{filename}' contains illegal characters."
            )

        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *{f"COM{i}" for i in range(1, 10)},
            *{f"LPT{i}" for i in range(1, 10)},
        }

        if filename.upper().split(".")[0] in reserved_names:
            raise ValueError(f"Filename '{filename}' is reserved on Windows.")

        if os.path.isdir(filename):
            raise ValueError(f"'{filename}' is a directory, not a file.")

        return None