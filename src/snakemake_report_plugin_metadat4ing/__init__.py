from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph
import requests
import json
import os
import importlib.util
import inspect
from snakemake_report_plugin_metadat4ing.interfaces import ParameterExtractorInterface

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
        self.get_context()
        self.param_counter = 0
        self.field_counter = 0
        self.param_dict = {}
        
        jsonld = {
            "@context": self.context_data.get('@context', {}),
            "@graph": []
        }
        jsonld['@context']['local'] = "https://local-domain.org/"
        jsonld['@context']['units'] = "http://qudt.org/vocab/unit/"

        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        main_steps = {job.rule for job in self.jobs}
        job_nodes, step_nodes, file_nodes, field_nodes = {}, {}, {}, {}
        file_counter = 0

        for i, step in enumerate(main_steps):
            step_nodes[step] = {
                "@id": f"local:main_processing_step_{i}",
                "@type": "processing step",
                "label": step
            }

        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_job_node(job, step_nodes, file_nodes, field_nodes, file_counter)
            job_nodes[job_label] = step_node
            file_counter = len(file_nodes)

        for key, value in self.param_dict.items():
            value["@id"] = key
        
        for d in (step_nodes, job_nodes, file_nodes, self.param_dict, field_nodes):
            jsonld["@graph"].extend(d.values())
        
        with open("report.jsonld", "w", encoding='utf8') as f:
            json.dump(jsonld, f, indent=4, ensure_ascii=False)

        self.create_ttl_from_jsonld(jsonld)

    def _create_job_node(self, job, main_steps_dict, files_dict, fields_dict, file_counter):
        node = {
            "@id": f"local:processing_step_{job.job.jobid}",
            "@type": "processing step",
            "label": f"{job.rule}_{job.job.jobid}",
            "part of": {"@id": main_steps_dict[job.rule]["@id"]},
            "start time": f"{datetime.fromtimestamp(job.starttime)}",
            "end time": f"{datetime.fromtimestamp(job.endtime)}",
            "has input": [],
            "has output": [],
            "has parameter": []
        }
        
        input_files = [f for j in self.dag.jobs if j.jobid == job.job.jobid for f in j.input]
        
        for file in input_files:
            file_node, file_counter = self._add_file(file, files_dict, file_counter)
            node["has input"].append({"@id": file_node["@id"]})
            if self.settings.paramscript:
                param_id_list, field_nodes = self._extract_parameters(job.rule, file, file_node)
                fields_dict.update(field_nodes)
                for param in param_id_list:
                    node["has parameter"].append({"@id": param})

        for file in job.output:
            file_node, file_counter = self._add_file(file, files_dict, file_counter)
            node["has output"].append({"@id": file_node["@id"]})

        return node

    def _add_file(self, file_path, file_dict, counter):
        if file_path not in file_dict:
            file_dict[file_path] = {
                "@id": f"local:file_{counter}",
                "@type": "cr:FileObject",
                "label": file_path
            }
            counter += 1
        return file_dict[file_path], counter

    def _extract_parameters(self, rule, file, file_node):
        param_id_list = []
        field_dict = {}
        extract_params_obj= self._load_param_extractor_obj()
        for name, data in extract_params_obj.extract_params(rule, file).items():
            name = name.replace("-", "_")
            param_id = ""
            param = {
                "@type": "text variable" if data['data-type'] == "schema:Text" else "numerical variable",
                "label": name,
            }
            if data['data-type'] == "schema:Text":
                param["has string value"] = data['value']
            else:
                param["has numerical value"] = data['value']
                if data['unit']:
                    param["has unit"] = {"@id": data['unit']}
            
            if param in self.param_dict.values():
                param_id = next((k for k, v in self.param_dict.items() if v == param), None)
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
                    "cr:extract": {"cr:jsonPath": data['json-path']}
                },
                **({"cr:dataType": data['data-type']} if data['data-type'] else {})
            }
            self.field_counter += 1
        return param_id_list, field_dict

    def get_context(self):
        url = "https://git.rwth-aachen.de/nfdi4ing/metadata4ing/metadata4ing/-/raw/master/m4i_context.jsonld"
        response = requests.get(url)
        if response.ok:
            self.context_data = response.json()
        else:
            print(f"Failed to fetch context data. Status code: {response.status_code}")

    def create_ttl_from_jsonld(self, data: dict):
        Graph().parse(data=data, format="json-ld").serialize("report.ttl", format="ttl")

    def add_dependencies(self):
        pass

    def _load_param_extractor_obj(self):
        script_path = self.settings.paramscript
        if not script_path or not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        spec = importlib.util.spec_from_file_location("extractor_module", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        extractor_class = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ParameterExtractorInterface) and obj is not ParameterExtractorInterface:
                extractor_class = obj
                break
        if extractor_class is None:
            raise ImportError("No subclass of ParameterExtractorInterface found in script")
        
        return extractor_class()
