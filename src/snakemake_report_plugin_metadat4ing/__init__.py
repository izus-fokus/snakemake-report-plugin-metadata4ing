from dataclasses import dataclass
from datetime import datetime
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase
from rdflib import Graph
import requests
import json

import os
from subprocess import run, CalledProcessError

@dataclass
class ReportSettings(ReportSettingsBase):
    pass

class Reporter(ReporterBase):
    def __post_init__(self):
        self.context_data = {}
    
    def render(self):
        self.get_context()
        jobs_dict = {}
        output_files_dict = {}
        file_counter = 0
        
        jsonld = {
            "@context": self.context_data['@context'],
            "@graph": []
        }
        jsonld['@context']['local'] = "https://local-domain.org/"
              
        sorted_jobs = sorted(self.jobs, key=lambda job: job.starttime)
        
        for i,j in self.rules.items():
            print(f"Rule: {i}")
            print(f"Output: {j.output}")
        
        for _, job in enumerate(sorted_jobs):
            job_label = f"{job.rule}_{job.job.jobid}"
            item = {
                "@id": f"local:processing_step_{job.job.jobid}",
                "@type": "processing step",
                "label": job_label,
                "start time": f"{datetime.fromtimestamp(job.starttime)}",
                "end time": f"{datetime.fromtimestamp(job.endtime)}",
                "has output": []
            }
            for file in job.output:
                if file not in output_files_dict:
                    output_files_dict[file] = {
                        "@id": f"local:output_file_{file_counter}",
                        "@type": "cr:FileObject",
                        "label": file
                    }
                    file_counter += 1
                item["has output"].append({"@id": output_files_dict[file]["@id"]})
            jobs_dict[job_label] = item
        
        # for target_job, dependent_jobs in self.dag.dependencies.items():
        #     for dependent_job in dependent_jobs:
        #         if dependent_job is not None:
        #             if dependent_job.rule.name in rules_dict and target_job.rule.name in rules_dict:
        #                 rules_dict[target_job.rule.name]["precedes"] = rules_dict[dependent_job.rule.name]["@id"]
        
        for _, item in jobs_dict.items():
            jsonld["@graph"].append(item)
        
        for _, item in output_files_dict.items():
            jsonld["@graph"].append(item)
        
        with open("report.jsonld", "w", encoding='utf8') as file:
            json.dump(jsonld, file, indent=4, ensure_ascii=False)
        
        self.create_ttl_from_jsonld(jsonld)
    
    def create_rulegraph(self):
        # images/rulegraph.svg should be something we can auto-generate. self.dag has methods dot()
        # and rule_dot() which can make the graph for us, but it still needs converting to SVG.
        # TODO: Replace hardcoded file paths with path provided to function
        #       (this will need to match the path given to the RO-Crate generator too)

        if os.path.exists("image/rulegraph.svg"):
           return True

        else:
            print("Auto generating 'image/rulegraph.svg'")
            try:
                with open("image/rulegraph.dot", "x") as dotfh:
                    print(self.dag.rule_dot(), file=dotfh)
            except FileExistsError:
                # Never mind, use the one we have. Maybe the user edited it.
                print("Using existing 'image/rulegraph.dot'")

            # For converting .dot to .svg I don't see a better way than calling the graphviz
            # program directly.
            try:
                run(['dot', '-Tsvg', 'image/rulegraph.dot', '-o', 'image/rulegraph.svg'],
                     check = True,
                     capture_output = True,
                     text = True)
            except CalledProcessError as e:
                print(str(e.stderr).rstrip())
                print("The 'dot' program returned the above error attempting to convert the rulegraph.")
                return False
            except FileNotFoundError as e:
                return False
            else:
                return True
                
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