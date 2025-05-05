from dataclasses import dataclass
from datetime import datetime
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph
import requests
import json

@dataclass
class ReportSettings(ReportSettingsBase):
    pass

class Reporter(ReporterBase):
    def __post_init__(self):
        self.context_data = {}
    
    def render(self):
        self.get_context()
        rules_dict = {}
        
        jsonld = {
            "@context": self.context_data['@context'],
            "@graph": []
        }
        jsonld['@context']['local'] = "https://local-domain.org/"
       
        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        
        for index, job in enumerate(sorted_jobs):
            item = {
                "@id": f"local:processing_step_{index}",
                "@type": "processing step",
                "label": f"{job.rule}",
                "start time": f"{datetime.fromtimestamp(job.starttime)}",
                "end time": f"{datetime.fromtimestamp(job.endtime)}"
            }
            rules_dict[job.rule] = item
        
        for target_job, dependent_jobs in self.dag.dependencies.items():
            for dependent_job in dependent_jobs:
                if dependent_job is not None:
                    if dependent_job.rule.name in rules_dict and target_job.rule.name in rules_dict:
                        rules_dict[target_job.rule.name]["precedes"] = rules_dict[dependent_job.rule.name]["@id"]
        
        for _, item in rules_dict.items():
            jsonld["@graph"].append(item)
        
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
            self.context_data = {}
            
    def create_ttl_from_jsonld(self, jsonld_data: dict):
        graph = Graph()
        graph.parse(data=jsonld_data, format="json-ld")
        graph.serialize("report.ttl", format="ttl")