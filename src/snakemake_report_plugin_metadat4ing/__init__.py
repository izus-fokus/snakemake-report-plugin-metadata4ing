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
        jobs_dict = {}
        files_dict = {}
        file_counter = 0
        main_processing_steps_dict = {}
        fields_dict = {}
        params_dict = {}
        param_counter = 0
        
        jsonld = {
            "@context": self.context_data['@context'],
            "@graph": []
        }
        jsonld['@context']['local'] = "https://local-domain.org/"
           
        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        main_processing_steps = {processing_steps.rule for processing_steps in self.jobs}
        
        for i, processing_step in enumerate(main_processing_steps):
            item = {
                "@id": f"local:main_processing_step_{i}",
                "@type": "processing step",
                "label": processing_step
            }
            main_processing_steps_dict[processing_step] = item
            
        for i, job in enumerate(sorted_jobs):
            job_label = f"{job.rule}_{job.job.jobid}"
            item = {
                "@id": f"local:processing_step_{job.job.jobid}",
                "@type": "processing step",
                "label": job_label,
                "part of": {"@id": main_processing_steps_dict[job.rule]["@id"]},
                "start time": f"{datetime.fromtimestamp(job.starttime)}",
                "end time": f"{datetime.fromtimestamp(job.endtime)}",
                "has input": [],
                "has output": [],
                "has parameter": []
            }
            
            for _job in self.dag.jobs:
                if _job.jobid == job.job.jobid:
                    for file in _job.input:
                        if file not in files_dict:
                            files_dict[file] = {
                                "@id": f"local:file_{file_counter}",
                                "@type": "cr:FileObject",
                                "label": file
                            }
                            file_counter += 1
                            params = self.extract_params(job.rule, file)
                            if params != {}:
                                for param_name, param_data in params.items():
                                    param_name = param_name.replace("-", "_")
                                    if param_data['data-type'] != None and param_data['data-type'] == "schema:Text":
                                        params_dict[f"{param_name}_{param_counter}"] = {
                                            "@id": f"local:variable_{param_name}_{param_counter}",
                                            "@type": "text variable",
                                            "label": param_name,
                                            "has string value": param_data['value'],
                                        }
                                    else:
                                        params_dict[f"{param_name}_{param_counter}"] = {
                                            "@id": f"local:variable_{param_name}_{param_counter}",
                                            "@type": "numerical variable",
                                            "label": param_name,
                                            "has numerical value": param_data['value']
                                        }
                                    if param_data['unit'] is not None:
                                        params_dict[f"{param_name}_{param_counter}"]["has unit"] = {"@id": param_data['unit']}
                                    fields_dict[f"{param_name}_{param_counter}"] = {
                                        "@id": f"local:field_{param_name}_{param_counter}",
                                        "@type": "cr:Field",
                                        "represents": {"@id": f"local:variable_{param_name}_{param_counter}"},
                                        "source": {
                                            "fileObject": {"@id": f"local:file_{file_counter}"},
                                            "extract": {
                                                "jsonPath": param_data['json-path']
                                            }
                                        }
                                    }
                                    if param_data['data-type'] is not None:
                                       fields_dict[f"{param_name}_{param_counter}"]["dataType"] = param_data['data-type']
                                    item["has parameter"].append({"@id": params_dict[f"{param_name}_{param_counter}"]["@id"]})
                                    param_counter += 1
                    item["has input"].append({"@id": files_dict[file]["@id"]})
            
            for file in job.output:
                if file not in files_dict:
                    files_dict[file] = {
                        "@id": f"local:file_{file_counter}",
                        "@type": "cr:FileObject",
                        "label": file
                    }
                    file_counter += 1
                item["has output"].append({"@id": files_dict[file]["@id"]})
            jobs_dict[job_label] = item
        
        for node in (main_processing_steps_dict, jobs_dict, files_dict, params_dict, fields_dict):
            jsonld["@graph"].extend(node.values())
        
        with open("report.jsonld", "w", encoding='utf8') as file:
            json.dump(jsonld, file, indent=4, ensure_ascii=False)
        
        self.create_ttl_from_jsonld(jsonld)
             
    def get_context(self):
        context_url = "https://git.rwth-aachen.de/nfdi4ing/metadata4ing/metadata4ing/-/raw/master/m4i_context.jsonld"
        response = requests.get(context_url)
        if response.status_code == 200:
            self.context_data = json.loads(response.text)
        else:
            print(f"Failed to fetch context data. Status code: {response.status_code}")
    
    def extract_params(self, rule_name:str, file_path:str):
        result = {}
        json_data = {}
        file_name = os.path.basename(file_path)
        if file_name.startswith("parameters_") and rule_name == "generate_input_files":
            with open(file_path) as f:
                json_data = json.load(f)
            for key, item in json_data.items():
                if isinstance(item, dict):
                    result[key] = {
                        'value': item['value'],
                        'unit': self.get_unit(key),
                        'json-path': f"/{key}/value",
                        'data-type':self.get_type(item['value'])
                    }
                else:
                    result[key] = {
                        'value': item,
                        'unit': None,
                        'json-path': f"/{key}",
                        'data-type':self.get_type(item)
                    }
        return result
            
    def add_dependencies(self):
        # for target_job, dependent_jobs in self.dag.dependencies.items():
        #     for dependent_job in dependent_jobs:
        #         if dependent_job is not None:
        #             if dependent_job.rule.name in rules_dict and target_job.rule.name in rules_dict:
        #                 rules_dict[target_job.rule.name]["precedes"] = rules_dict[dependent_job.rule.name]["@id"]
        pass 
          
    def create_ttl_from_jsonld(self, jsonld_data: dict):
        graph = Graph()
        graph.parse(data=jsonld_data, format="json-ld")
        graph.serialize("report.ttl", format="ttl")
    
    def get_unit(self, param_name: str):
        if param_name == "young-modulus":
            return "units:PA"
        elif param_name == "load":
            return "unit:MegaPA"
        elif param_name == "length" or param_name == "radius" or param_name == "element-size":
            return "unit:m"
        return None
    
    def get_type(self, param_value: any):
        if isinstance(param_value,float):
            return "schema:Float"
        elif isinstance(param_value,float):
            return "schema:Integer"
        elif isinstance(param_value,str):
            return "schema:Text"
        return None