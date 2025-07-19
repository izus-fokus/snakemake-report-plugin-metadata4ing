from dataclasses import dataclass, field
from datetime import datetime
from fileinput import filename
from pathlib import Path
from typing import Optional
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph
import requests
import json
import importlib.util
import inspect
from snakemake_report_plugin_metadat4ing.interfaces import (
    ParameterExtractorInterface,
)
from rocrate.rocrate import ROCrate
from rocrate.model.softwareapplication import SoftwareApplication
import mimetypes
import shlex
import os
import hashlib

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


class Reporter(ReporterBase):
    def __post_init__(self):
        self.context_data = {}

    def render(self):
        self._get_context()
        self.param_counter = 0
        self.field_counter = 0
        self.param_dict = {}
        self.conda_envs_dict = {}
        self.tool_counter = 0
        self.tools_dict = {}
        self.crate = ROCrate()
        self.simulation_hash = ""
        self.provenance_filename = "provenance.jsonld"
        self.provenance_ttl_filename = "provenance.ttl"

        jsonld = {
            "@context": self.context_data.get("@context", {}),
            "@graph": [],
        }
        jsonld["@context"]["units"] = "http://qudt.org/vocab/unit/"

        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        job_nodes, step_nodes, file_nodes, field_nodes = {}, {}, {}, {}
        file_counter = 0
        
        toposorted = self.dag.toposorted()
        
        for i, steps in enumerate(toposorted):
            for step in steps:
                step_nodes[f"{step}"] = {
                    "@id": f"local:{step}",
                    "@type": "processing step",
                    "label": f"{step}",
                    "schema:position": i,
                }
        
        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_job_node(
                job, step_nodes, file_nodes, field_nodes, file_counter
            )
            job_nodes[job_label] = step_node
            file_counter = len(file_nodes)

        for key, value in self.param_dict.items():
            value["@id"] = key

        for d in (
            step_nodes,
            job_nodes,
            file_nodes,
            self.param_dict,
            field_nodes,
            self.tools_dict,
        ):
            jsonld["@graph"].extend(d.values())

        self.simulation_hash = self._random_hash_from_json(jsonld,16)
        jsonld["@context"]["local"] = f"https://local-domain.org/{self.simulation_hash}/"
            
        with open("provenance.jsonld", "w", encoding="utf8") as f:
            json.dump(jsonld, f, indent=4, ensure_ascii=False)
        
        self._create_ttl_from_jsonld(jsonld)
        self._add_ro_crate_file_nodes(file_nodes)
        # self._add_ro_crate_software()
        self._create_ro_crate_file()
        
        os.remove(self.provenance_filename)
        os.remove(self.provenance_ttl_filename)
   
    def _create_job_node(
        self, job, main_steps_dict, files_dict, fields_dict, file_counter
    ):
        node = {
            "@id": f"local:processing_step_{job.job.jobid}",
            "@type": "processing step",
            "label": f"{job.rule}_{job.job.jobid}",
            "part of": {"@id": main_steps_dict[job.rule]["@id"]},
            "start time": f"{datetime.fromtimestamp(job.starttime)}",
            "end time": f"{datetime.fromtimestamp(job.endtime)}",
            "has input": [],
            "has output": [],
            "has parameter": [],
            "has employed tool": [],
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
            j.shellcmd for j in self.dag.jobs if j.jobid == job.job.jobid and j.shellcmd
        ]
        
        for shell_cmd_file in shell_cmds:
            shell_file = self._extract_script(shell_cmd_file)
            if shell_file:
                _ = self.crate.add_file(
                    shell_file,
                    dest_path=shell_file,
                    properties={
                        "name": shell_file,
                        "encodingFormat": self._get_mime_type(shell_file),
                    },
            )
            
        for conda_file in conda_files:
            if (
                self.settings.paramscript
                and conda_file
                and conda_file not in self.conda_envs_dict
            ):
                tools = self._extract_tools(job.rule, conda_file.content)
                for tool in tools:
                    node["has employed tool"].append({"@id": tool["@id"]})

        for file in input_files:
            if not self.is_file(file):
                continue
            file_node, file_counter = self._add_file(
                file, files_dict, file_counter
            )
            node["has input"].append({"@id": file_node["@id"]})
            if self.settings.paramscript:
                param_id_list, field_nodes = self._extract_parameters(
                    job.rule, file, file_node
                )
                fields_dict.update(field_nodes)
                for param in param_id_list:
                    node["has parameter"].append({"@id": param})

        for file in job.output:
            if not self.is_file(file):
                continue
            file_node, file_counter = self._add_file(
                file, files_dict, file_counter
            )
            node["has output"].append({"@id": file_node["@id"]})
            if self.settings.paramscript:
                param_id_list, field_nodes = self._extract_parameters(
                    job.rule, file, file_node
                )
                fields_dict.update(field_nodes)
        snakefile, snakepath = self._find_snakefile()
        
        if snakefile:
            _ = self.crate.add_file(
                    snakefile,
                    dest_path=snakepath,
                    properties={
                        "name": snakefile,
                        "encodingFormat": "text/plain",
                    },
            )
            
        return node

    def _add_file(self, file_path, file_dict, counter):
        if file_path not in file_dict:
            file_dict[file_path] = {
                "@id": file_path,
                "@type": "cr:FileObject",
                "label": file_path,
            }
            counter += 1
        return file_dict[file_path], counter

    def _extract_parameters(self, rule, file, file_node):
        param_id_list = []
        field_dict = {}
        extract_params_obj = self._load_param_extractor_obj()
        params = extract_params_obj.extract_params(rule, file)
        if params:
            params = self._validate_extract_param_output(params)
            for name, data in params.items():
                name = name.replace("-", "_")
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
                        param["has unit"] = {"@id": data["unit"]}

                if param in self.param_dict.values():
                    param_id = next(
                        (k for k, v in self.param_dict.items() if v == param),
                        None,
                    )
                    param_id_list.append(param_id)
                else:
                    param_id = f"local:variable_{name}_{self.param_counter}"
                    self.param_dict[param_id] = param
                    self.param_counter += 1

                field_dict[f"{name}_{self.field_counter}"] = {
                    "@id": f"local:field_{name}_{self.field_counter}",
                    "@type": "Field",
                    "represents": {"@id": param_id},
                    "source": {
                        "file object": {"@id": file_node["@id"]},
                        "cr:extract": {"cr:jsonPath": data["json-path"]},
                    },
                    **(
                        {"cr:dataType": data["data-type"]}
                        if data["data-type"]
                        else {}
                    ),
                }
                self.field_counter += 1
        return param_id_list, field_dict

    def _extract_tools(self, rule, file):
        tools_list = []
        extract_params_obj = self._load_param_extractor_obj()
        tools = extract_params_obj.extract_tools(rule, file)
        if tools:
            tools = self._validate_extract_tools_output(tools)
            for name, version in tools.items():
                if name not in self.tools_dict:
                    item = {
                        "@id": f"local:tool_{self.tool_counter}",
                        "@type": "schema:SoftwareApplication",
                        "label": name,
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

    def _get_context(self):
        # url = "https://git.rwth-aachen.de/nfdi4ing/metadata4ing/metadata4ing/-/raw/master/m4i_context.jsonld"
        url = "https://git.rwth-aachen.de/nfdi4ing/metadata4ing/metadata4ing/-/raw/master/m4i2rocrate_context.jsonld"
        response = requests.get(url)
        if response.ok:
            self.context_data = response.json()
        else:
            print(
                f"Failed to fetch context data. Status code: {response.status_code}"
            )

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

    def _add_ro_crate_software(self):
        self.crate.add(SoftwareApplication(self.crate, "Snakemake", {
            "name": "Snakemake",
            "url": "https://snakemake.readthedocs.io/"
        }))
    
    def _create_ttl_from_jsonld(self, data: dict):
        Graph().parse(data=data, format="json-ld").serialize(
            "provenance.ttl", format="ttl"
        )

    def _create_ro_crate_file(self):
        self.crate.write_zip(f"ro-crate-metadata-{self.simulation_hash}.zip")

    def _load_param_extractor_obj(self):
        script_path = self.settings.paramscript
        if not script_path or not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        spec = importlib.util.spec_from_file_location(
            "extractor_module", script_path
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

    def _validate_extract_param_output(self, result):
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")
        for key, value in result.items():
            if not isinstance(key, str):
                raise TypeError(f"Key '{key}' must be a string.")
            if not isinstance(value, dict):
                raise TypeError(f"Value for key '{key}' must be a dictionary.")
            required_keys = ["value", "unit", "json-path", "data-type"]
            for rk in required_keys:
                if rk not in value:
                    raise ValueError(
                        f"Missing key '{rk}' in value for '{key}'."
                    )
            if value["unit"] and not isinstance(value["unit"], str):
                raise TypeError(f"'unit' for '{key}' must be a string.")
            if not isinstance(value["json-path"], str):
                raise TypeError(f"'json-path' for '{key}' must be a string.")
            if not isinstance(value["data-type"], str):
                raise TypeError(f"'data-type' for '{key}' must be a string.")
        return result

    def _validate_extract_tools_output(self, result):
        if not isinstance(result, dict):
            raise TypeError("Function output must be a dictionary.")
        for key, value in result.items():
            if not isinstance(key, str):
                raise TypeError(f"Key '{key}' must be a string.")
        return result

    def _get_mime_type(self, file_name: str) -> str:
        """
        Return the MIME type that corresponds to a file’s extension.

        Parameters
        ----------
        file_name : str
            A file name (or full path) that includes an extension, e.g. 'report.pdf'.

        Returns
        -------
        str
            The detected MIME type, e.g. 'application/pdf'.
            Falls back to 'application/octet-stream' if the type is unknown.
        """
        # Ensure we’re only passing the name, not a PosixPath object, to mimetypes.
        file_name = Path(file_name).name

        mime_type, _ = mimetypes.guess_type(file_name, strict=False)
        return mime_type or "application/octet-stream"

    def _extract_script(self, cmd: str) -> str | None:
       """
       Return the script filename from a shell‑command string, or None
       if no plausible script can be identified.
       """
       _INTERPRETERS = {
            "python", "python3", "python2",
            "pypy", "pypy3",
            "ruby", "perl", "node", "deno", "php", "lua",
            "Rscript", "R", "bash", "sh", "zsh", "ksh", "fish"
        }
       
       try:
           tokens = shlex.split(cmd, posix=True)
       except ValueError: 
           return None

       if not tokens:
           return None

       if Path(tokens[0]).name in _INTERPRETERS:
           for tok in tokens[1:]:
               if tok.startswith("-"):
                   continue
               return Path(tok).name 
           return None

       first = Path(tokens[0])
       
       if first.suffix and first.suffix not in {".exe", ".bat", ".cmd"}:
           return first.name

       return None
   
    def _find_snakefile(self):
        current_dir = os.getcwd()
        for file in os.listdir(current_dir):
            if file.lower() == "snakefile":
                rel_path = os.path.relpath(os.path.join(current_dir, file))
                return (file, rel_path)
        return None
    
    def is_file(self, file_name: str) -> bool:
        return (
            os.path.basename(file_name) == file_name and  # No path component
            not os.path.isabs(file_name) and              # Not an absolute path
            not any(sep in file_name for sep in ['/', '\\'])  # No separators
        )
    def _random_hash_from_json(self, json_content: dict, length=8) -> str:
        json_str = json.dumps(json_content, sort_keys=True).encode('utf-8')
        hash_value = hashlib.sha256(json_str).hexdigest()
        return hash_value[:length]