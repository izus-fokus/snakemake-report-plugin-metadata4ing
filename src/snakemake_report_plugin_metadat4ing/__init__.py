from dataclasses import dataclass
from datetime import datetime
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph
import requests
import json
import os

@dataclass
class ReportSettings(ReportSettingsBase):
    pass

class Reporter(ReporterBase):
    def __post_init__(self):
        self.context_data = {}

    def render(self):
        self.get_context()

        jsonld = {
            "@context": self.context_data.get('@context', {}),
            "@graph": []
        }
        jsonld['@context']['local'] = "https://local-domain.org/"

        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        main_steps = {job.rule for job in self.jobs}
        job_nodes, step_nodes, file_nodes, field_nodes, param_nodes = {}, {}, {}, {}, {}
        file_counter, param_counter = 0, 0

        # Build main steps
        for i, step in enumerate(main_steps):
            step_nodes[step] = {
                "@id": f"local:main_processing_step_{i}",
                "@type": "processing step",
                "label": step
            }

        # Process jobs
        for job in sorted_jobs:
            job_label = f"{job.rule}_{job.job.jobid}"
            step_node = self._create_job_node(job, step_nodes, file_nodes, field_nodes, param_nodes, file_counter, param_counter)
            job_nodes[job_label] = step_node
            file_counter = len(file_nodes)
            param_counter = len(param_nodes)

        # Combine all RDF graph nodes
        for d in (step_nodes, job_nodes, file_nodes, param_nodes, field_nodes):
            jsonld["@graph"].extend(d.values())

        with open("report.jsonld", "w", encoding='utf8') as f:
            json.dump(jsonld, f, indent=4, ensure_ascii=False)

        self.create_ttl_from_jsonld(jsonld)

    def _create_job_node(self, job, main_steps_dict, files_dict, fields_dict, params_dict, file_counter, param_counter):
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
            param_nodes, field_nodes, param_counter = self._extract_parameters(job.rule, file, file_node, param_counter)
            params_dict.update(param_nodes)
            fields_dict.update(field_nodes)
            node["has parameter"].extend({"@id": p["@id"]} for p in param_nodes.values())

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

    def _extract_parameters(self, rule, file, file_node, counter):
        param_dict, field_dict = {}, {}
        for name, data in self.extract_params(rule, file).items():
            name = name.replace("-", "_")
            var_id = f"local:variable_{name}_{counter}"
            param = {
                "@id": var_id,
                "@type": "text variable" if data['data-type'] == "schema:Text" else "numerical variable",
                "label": name,
            }
            if data['data-type'] == "schema:Text":
                param["has string value"] = data['value']
            else:
                param["has numerical value"] = data['value']
                if data['unit']:
                    param["has unit"] = {"@id": data['unit']}
            param_dict[f"{name}_{counter}"] = param

            field_dict[f"{name}_{counter}"] = {
                "@id": f"local:field_{name}_{counter}",
                "@type": "cr:Field",
                "represents": {"@id": var_id},
                "source": {
                    "fileObject": {"@id": file_node["@id"]},
                    "extract": {"jsonPath": data['json-path']}
                },
                **({"dataType": data['data-type']} if data['data-type'] else {})
            }
            counter += 1
        return param_dict, field_dict, counter

    def get_context(self):
        url = "https://git.rwth-aachen.de/nfdi4ing/metadata4ing/metadata4ing/-/raw/master/m4i_context.jsonld"
        response = requests.get(url)
        if response.ok:
            self.context_data = response.json()
        else:
            print(f"Failed to fetch context data. Status code: {response.status_code}")

    def extract_params(self, rule_name: str, file_path: str):
        results = {}
        file_name = os.path.basename(file_path)
        if file_name.startswith("parameters_") and rule_name == "generate_input_files":
            with open(file_path) as f:
                data = json.load(f)
            for key, val in data.items():
                if isinstance(val, dict):
                    results[key] = {
                        'value': val['value'],
                        'unit': self.get_unit(key),
                        'json-path': f"/{key}/value",
                        'data-type': self.get_type(val['value'])
                    }
                else:
                    results[key] = {
                        'value': val,
                        'unit': None,
                        'json-path': f"/{key}",
                        'data-type': self.get_type(val)
                    }
        return results

    def get_unit(self, name: str):
        return {
            "young-modulus": "units:PA",
            "load": "unit:MegaPA",
            "length": "unit:m",
            "radius": "unit:m",
            "element-size": "unit:m"
        }.get(name)

    def get_type(self, val):
        if isinstance(val, float):
            return "schema:Float"
        elif isinstance(val, int):
            return "schema:Integer"
        elif isinstance(val, str):
            return "schema:Text"
        return None

    def create_ttl_from_jsonld(self, data: dict):
        Graph().parse(data=data, format="json-ld").serialize("report.ttl", format="ttl")

    def add_dependencies(self):
        pass
