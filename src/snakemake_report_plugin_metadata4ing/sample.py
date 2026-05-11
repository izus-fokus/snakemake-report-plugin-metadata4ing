import os
from datetime import datetime, timezone
import requests
import uuid


from dataclasses import dataclass, field
from typing import Any, Optional

from rocrate.model import (
    ComputationalWorkflow,
    ContextEntity,
    DataEntity,
    Dataset,
    File,
    Person,
    Preview,
)
from rocrate.rocrate import ROCrate

import spdx_license_list

from snakemake.logging import logger as snakemake_logger
from snakemake_interface_common.exceptions import WorkflowError
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase

# Raise errors that will not be handled within this plugin but thrown upwards to
# Snakemake and the user as WorkflowError.
from snakemake_interface_common.exceptions import WorkflowError  # noqa

from pathlib import Path

# Optional:
# Define additional settings for your reporter.
# They will occur in the Snakemake CLI as --report-<reporter-name>-<param-name>
# Omit this class if you don't need any.
# Make sure that all defined fields are Optional (or bool) and specify a default value
# of None (or False) or anything else that makes sense in your case.
@dataclass
class ReportSettings(ReportSettingsBase): # type: ignore[misc]
    run_name: Optional[str] = field(
        default="Workflow Run RO-Crate",
        metadata={
            "help": "Use a descriptive name for your workflow run. "
            "This SHOULD identify the run to humans well enough to disambiguate it from other workflow runs. "
            "If not set, a generic non-descriptive name will be used.",
            "env_var": False,
            "required": False,
        },
    )
    run_description: Optional[str] = field(
        default="Generic Description",
        metadata={
            "help": "Use this field to describe the workflow run in more detail, "
            "including why it was executed, in what context, and why the resulting dataset matters. "
            "If not set, a generic description will be used.",
            "env_var": False,
            "required": False,
        },
    )
    run_license: Optional[str] = field(
        default="CC-BY-4.0",
        metadata={
            "help": "The Crate MUST specify a license. "
            "The license is assumed to apply to any content of the crate, unless overriden by license on individual File entities. "
            "Please specify a SPDX license tag or specify the URL to the license. "
            "For a list of SPDX license tags see: https://spdx.github.io/spdx-spec/v2.3/SPDX-license-list/ "
            "If not set, CC-BY-4.0",
            "env_var": False,
            "required": False,
        },
    )
    researcher_orcid: Optional[str] = field(
        default=None,
        metadata={
            "help": "Specify the ORCID iD of the person executing the workflow run. "
            "This uniquely identifies the responsible researcher who executed the workflow run.",
            "env_var": False,
            "required": False,
        },
    )
    researcher_name: Optional[str] = field(
        default=None,
        metadata={
            "help:": "Specify the full name of the researcher responsible for running the workflow. "
            "This will be recorded in the metadata.",
            "env_var": False,
            "required": False,
        },
    )
    organization_ror: Optional[str] = field(
        default=None,
        metadata={
            "help:": "Use a ROR ID (Research Organization Registry) to uniquely identify a research organization. "
            "This will be used as the researcher's affiliation and recorded in the metadata.",
            "env_var": False,
            "required": False,
        },
    )


# Required:
# Implementation of your reporter
class Reporter(ReporterBase): # type: ignore[misc]
    wf_crate: ROCrate
    valid_spdx_identifier: bool
    valid_ror_identifier: bool

    author_props: dict[str, Any]
    org_props: dict[str, Any]

    def __post_init__(self) -> None:
        # initialize additional attributes
        # Do not overwrite the __init__ method as this is kept in control of the base
        # class in order to simplify the update process.
        # See https://github.com/snakemake/snakemake-interface-report-plugins/snakemake_interface_report_plugins/reporter.py # noqa: E501
        # for attributes of the base class.
        # In particular, the settings of above ReportSettings class are accessible via
        # self.settings.
        self.logger: Any = snakemake_logger
        self.author_props = {}
        self.org_props = {"@type": "Organization"}

    def render(self) -> None:
        # Validate Settings
        self.validate_settings()

        # Render the report, using attributes of the base class.

        # Path to main Snakefile!
        main_snakefile = self.dag.workflow.main_snakefile
        print("Main snakefile: " + main_snakefile)

        # Base path for the RO-Crate. By default this is the directory containing the Snakefile
        base_path = os.path.dirname(main_snakefile)

        self.wf_crate = ROCrate()

        workflow_path = Path(main_snakefile)
        include_files: list[Path] = []
        self.wf_crate.add_workflow(
            workflow_path,
            workflow_path.name,
            fetch_remote=False,
            main=True,
            lang="snakemake",
            gen_cwl=False,
        )

        # Set encoding format for main Snakefile
        self.wf_crate.mainEntity["encodingFormat"] = "text/x-python"

        for file_entry in include_files:
            self.wf_crate.add_file(file_entry)

        # Add Workflow Run RO-Crate context to ro-crate-metadata.json
        self.wf_crate.metadata.extra_contexts.append(
            "https://w3id.org/ro/terms/workflow-run/context"
        )

        # Add "conformsTo" statements to RootDataset "./"
        self.wf_crate.root_dataset.append_to(
            "conformsTo", {"@id": "https://w3id.org/ro/wfrun/process/0.5"}
        )
        self.wf_crate.root_dataset.append_to(
            "conformsTo", {"@id": "https://w3id.org/ro/wfrun/workflow/0.5"}
        )
        self.wf_crate.root_dataset.append_to(
            "conformsTo", {"@id": "https://w3id.org/ro/wfrun/provenance/0.5"}
        )
        self.wf_crate.root_dataset.append_to(
            "conformsTo", {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"}
        )

        # Add CreativeWork entities that correspond to previosly added "conformsTo" statements
        self.wf_crate.add(
            ContextEntity(
                self.wf_crate,
                "https://w3id.org/ro/wfrun/process/0.5",
                properties={
                    "@type": "CreativeWork",
                    "name": "Process Run Crate",
                    "version": "0.5",
                },
            )
        )
        self.wf_crate.add(
            ContextEntity(
                self.wf_crate,
                "https://w3id.org/ro/wfrun/workflow/0.5",
                properties={
                    "@type": "CreativeWork",
                    "name": "Workflow Run Crate",
                    "version": "0.5",
                },
            )
        )
        self.wf_crate.add(
            ContextEntity(
                self.wf_crate,
                "https://w3id.org/ro/wfrun/provenance/0.5",
                properties={
                    "@type": "CreativeWork",
                    "name": "Provenance Run Crate",
                    "version": "0.5",
                },
            )
        )
        self.wf_crate.add(
            ContextEntity(
                self.wf_crate,
                "https://w3id.org/workflowhub/workflow-ro-crate/1.0",
                properties={
                    "@type": "CreativeWork",
                    "name": "Workflow RO-Crate",
                    "version": "1.0",
                },
            )
        )

        # Set Root Data Entity name property
        self.wf_crate.name = self.settings.run_name

        # Set Root Data Entity description property
        self.wf_crate.description = self.settings.run_description

        # Set Root Data Entity license property
        self.add_license()

        self.author_props = {"name": self.settings.researcher_name}

        # Add an Organization (using ROR ID as @id)
        if self.settings.organization_ror:
            org = ContextEntity(
                self.wf_crate,
                identifier=self.settings.organization_ror,
                properties=self.org_props,
            )
            self.wf_crate.add(org)
            self.author_props["affiliation"] = {"@id": org.id}

        # Add author to RO-Crate
        author = self.wf_crate.add(
            Person(
                self.wf_crate,
                self.settings.researcher_orcid,
                self.author_props,
            )
        )
        self.wf_crate.root_dataset["author"] = author

        # Add publisher to RO-Crate
        # https://www.researchobject.org/ro-crate/specification/1.1/contextual-entities.html#publisher
        if self.settings.organization_ror:
            self.wf_crate.root_dataset["publisher"] = org
        else:
            self.wf_crate.root_dataset["publisher"] = author

        # TODO Add workflow input files to metadata

        # TODO Add workflow output files to metadata
        # outputs = [ofile for job in self.jobs for ofile in job.output]

        # Add workflow run as CreateAction
        # Snakemake (to my knowledge) does not create an unique identifier for a run
        start_times = [job_record.starttime for job_record in self.jobs]
        end_times = [job_record.endtime for job_record in self.jobs]

        earliest_start = min(start_times)
        latest_end = max(end_times)

        # convert to local time with timezone info. Format as ISO 8601 with offset
        earliest_start_dt = (
            datetime.fromtimestamp(earliest_start).astimezone().isoformat()
        )
        latest_end_dt = datetime.fromtimestamp(latest_end).astimezone().isoformat()

        run_id = str(uuid.uuid4())
        self.wf_crate.add(
            ContextEntity(
                self.wf_crate,
                ("#" + run_id),
                properties={
                    "@type": "CreateAction",
                    "name": "Snakemake workflow run " + run_id,
                    "startTime": earliest_start_dt,
                    "endTime": latest_end_dt,
                    "instrument": {"@id": self.wf_crate.mainEntity.id},
                },
            )
        )

        # Write only metadata file
        self.wf_crate.metadata.write(base_path)

        # If we get the rocrate-metadata.json, we could write only the metadata?
        # writable_entity.write(base_path)

        # The reporter has following properties:
        # rules: Mapping[str, RuleRecordInterface],
        # results: Mapping[
        #    CategoryInterface, Mapping[CategoryInterface, List[RuleRecordInterface]]
        # ],
        # configfiles: List[ConfigFileRecordInterface],
        # jobs: List[JobRecordInterface],
        # settings: ReportSettingsBase,
        # workflow_description: str,
        # dag: DAGReportInterface,
        # metadata: Optional[

        # print("rules: " + str(self.rules))
        # rules: {'c': RuleRecord(name='c', container_img_url=None, conda_env=None, n_jobs=1, id=UUID('dd49d5c6-8b39-492b-9f76-ff7d7c5b8b7d'), language='bash', source='cp {input} {output} 2> {log}'), 'b': RuleRecord(name='b', container_img_url=None, conda_env=None, n_jobs=1, id=UUID('697928a7-dce9-40eb-bcdb-a85956d51b30'), language='bash', source='cp {input} {output} 2> {log}'), 'a': RuleRecord(name='a', container_img_url=None, conda_env=None, n_jobs=1, id=UUID('ab982ff7-dc45-4106-a2bf-abdd1a01e709'), language='bash', source='touch {output} 2> {log}'), 'd': RuleRecord(name='d', container_img_url=None, conda_env=None, n_jobs=2, id=UUID('eb60b3b1-8029-40a5-9418-44277886e4cd'), language='bash', source='touch {output}')}

        print("results: " + str(self.results))
        # results: defaultdict(<function auto_report.<locals>.<lambda> at 0x7f0eb287bce0>, {Category(name='Test', is_other=False, id='532eaabd9574880dbf76b9b8cc00832c20a6ec113d682299550d7a6e0f345e25'): defaultdict(<class 'list'>, {Category(name='Subtest', is_other=False, id='27e33cf3d08386e66c6bd6fc3c561200cb72fdf3e323cca5e3e84e3f52ebd533'): [FileRecord(path=PosixPath('test3.out'), job=c, parent_path=None, category=Category(name='Test', is_other=False, id='532eaabd9574880dbf76b9b8cc00832c20a6ec113d682299550d7a6e0f345e25'), wildcards_overwrite=None, labels={'label1': 'foo', 'label2': 'bar'}, raw_caption=<snakemake.sourcecache.LocalSourceFile object at 0x7f0eb46283d0>, aux_files=[], name_overwrite=None, size=0, params='', wildcards='', mime='text/plain', caption='<p>This is a test caption test3.out.</p>\n', id='ca8614f357ffb0420b2fb322516bd910913a9e364418ad286bb55ad0b410276c', target='test3.out')]})})

        # print("configfiles: " + str(self.configfiles))
        # configfiles: []

        print("jobs: " + str(self.jobs))
        # jobs: [JobRecord(job=a, rule='a', starttime=1758359937.1033478, endtime=1758359937.106027, output=['test1.out'], conda_env_file=None, container_img_url=None), JobRecord(job=b, rule='b', starttime=1758359937.1131978, endtime=1758359937.115347, output=['test2.out'], conda_env_file=None, container_img_url=None), JobRecord(job=c, rule='c', starttime=1758359937.1213574, endtime=1758359937.1234777, output=['test3.out'], conda_env_file=None, container_img_url=None), JobRecord(job=d, rule='d', starttime=1758359937.0977733, endtime=1758359937.1033478, output=['res/somedir1.out'], conda_env_file=None, container_img_url=None), JobRecord(job=d, rule='d', starttime=1758359937.101454, endtime=1758359937.1047735, output=['res/somedir2/subdir.out'], conda_env_file=None, container_img_url=None)]

        print("settings: " + str(self.settings))
        # settings: None

        # print("workflow_description: " + str(self.workflow_description))
        # ""

        print("dag.workflow: " + str(self.dag.workflow))
        # dag.workflow: Workflow(config_settings=ConfigSettings(config=immutables.Map({}), configfiles=[], config_args=[], replace_workflow_config=False), resource_settings=ResourceSettings(cores=1, nodes=None, local_cores=None, max_threads=None, resources=immutables.Map({}), overwrite_threads=immutables.Map({}), overwrite_scatter=immutables.Map({}), overwrite_resource_scopes=immutables.Map({}), overwrite_resources=immutables.Map({}), default_resources=<snakemake.resources.DefaultResources object at 0x7facb6d1c830>), workflow_settings=WorkflowSettings(wrapper_prefix=None, exec_mode=<ExecMode.DEFAULT: 0>, cache=None, consider_ancient={}), storage_settings=StorageSettings(default_storage_provider=None, default_storage_prefix=None, shared_fs_usage=frozenset({<SharedFSUsage.STORAGE_LOCAL_COPIES: 4>, <SharedFSUsage.SOURCE_CACHE: 5>, <SharedFSUsage.SOURCES: 3>, <SharedFSUsage.INPUT_OUTPUT: 1>, <SharedFSUsage.SOFTWARE_DEPLOYMENT: 2>, <SharedFSUsage.PERSISTENCE: 0>}), keep_storage_local=False, retrieve_storage=True, local_storage_prefix=PosixPath('.snakemake/storage'), remote_job_local_storage_prefix=PosixPath('.snakemake/storage'), omit_flags=frozenset(), notemp=False, all_temp=False, unneeded_temp_files=frozenset(), wait_for_free_local_storage=None), dag_settings=DAGSettings(targets=frozenset(), target_jobs=frozenset(), target_files_omit_workdir_adjustment=False, batch=None, forcetargets=False, forceall=False, forcerun=frozenset(), until=frozenset(), omit_from=frozenset(), force_incomplete=False, allowed_rules=frozenset(), rerun_triggers=frozenset({<RerunTrigger.PARAMS: 1>, <RerunTrigger.MTIME: 0>, <RerunTrigger.CODE: 4>, <RerunTrigger.SOFTWARE_ENV: 3>, <RerunTrigger.INPUT: 2>}), max_inventory_wait_time=20, trust_io_cache=False, max_checksum_file_size=1000000, strict_evaluation=frozenset(), print_dag_as=<PrintDag.DOT: 0>), execution_settings=ExecutionSettings(latency_wait=5, keep_going=False, debug=False, standalone=False, ignore_ambiguity=False, lock=True, ignore_incomplete=False, wait_for_files=(), no_hooks=False, retries=0, attempt=1, use_threads=False, shadow_prefix=None, keep_incomplete=False, keep_metadata=True, edit_notebook=None, cleanup_scripts=True, queue_input_wait_time=10), deployment_settings=DeploymentSettings(deployment_method=frozenset(), conda_prefix=None, conda_cleanup_pkgs=None, conda_base_path=None, conda_frontend='conda', conda_not_block_search_path_envvars=False, apptainer_args='', apptainer_prefix=None), scheduling_settings=SchedulingSettings(prioritytargets=frozenset(), scheduler='ilp', ilp_solver=None, solver_path=None, greediness=1.0, subsample=None, max_jobs_per_second=None, max_jobs_per_timespan=None), output_settings=OutputSettings(dryrun=False, printshellcmds=False, nocolor=False, quiet=None, debug_dag=False, verbose=True, show_failed_logs=True, log_handler_settings=immutables.Map({}), keep_logger=False, stdout=False, benchmark_extended=False), remote_execution_settings=RemoteExecutionSettings(jobname='snakejob.{rulename}.{jobid}.sh', jobscript=None, max_status_checks_per_second=100.0, seconds_between_status_checks=0, container_image='snakemake/snakemake:v9.11.2', preemptible_retries=None, preemptible_rules=PreemptibleRules(rules=frozenset(), all=False), envvars=[], immediate_submit=False, precommand=None, job_deploy_sources=True), group_settings=GroupSettings(overwrite_groups=immutables.Map({}), group_components=immutables.Map({}), local_groupid='local'), executor_settings=None, storage_provider_settings={}, global_report_settings=None, check_envvars=True, cache_rules={'all': False, 'a': False, 'b': False, 'c': False, 'd': False}, overwrite_workdir=PosixPath('/tmp/pytest-of-fbartusch/pytest-17/test_simple_workflow0/simple'), _workdir_handler=None, injected_conda_envs=[])

        print(
            "self.dag.workflow.config_settings: "
            + str(self.dag.workflow.config_settings)
        )
        # self.dag.workflow.config_settings: ConfigSettings(config=immutables.Map({}), configfiles=[], config_args=[], replace_workflow_config=False)

        # print("metadata: " + str(self.metadata))
        # metadata: {}

    def validate_settings(self) -> None:
        # Check valid SPDX identifier.
        self.valid_spdx_identifier = (
            self.settings.run_license in spdx_license_list.LICENSES
        )
        if not self.valid_spdx_identifier:
            self.logger.warning(
                "License '%s' is not a valid SPDX identifier. "
                "Consider using one from https://spdx.org/licenses/",
                self.settings.run_license,
            )

        # Check valid ROR identifier
        ror_id = (
            self.settings.organization_ror
        )  # you can also pass "https://ror.org/04fa4r504"
        ror_url = f"https://api.ror.org/organizations/{ror_id.split('/')[-1]}"

        try:
            resp = requests.get(ror_url)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP error: {e}")
            self.valid_ror_identifier = False
        except requests.exceptions.RequestException as e:
            # This catches other errors (connection, timeout, etc.)
            print(f"Request failed: {e}")
            self.valid_ror_identifier

        self.valid_ror_identifier = True

        # self.org_props = {"name": self.settings.researcher_name}

        org = resp.json()
        # Search for an URL (links -> type: "website")
        for link in org["links"]:
            if link["type"] == "website":
                self.org_props["url"] = link["value"]

        # Search for the name (entry in "names" with type "ror_display", "label"
        for name in org["names"]:
            if "ror_display" in name["types"]:
                self.org_props["name"] = name["value"]

    def add_license(self) -> None:
        if self.valid_spdx_identifier:
            self.wf_crate.license = {
                "@id": "http://spdx.org/licenses/" + self.settings.run_license
            }
            self.wf_crate.add(
                ContextEntity(
                    self.wf_crate,
                    self.wf_crate.license,
                    properties={
                        "@type": "CreativeWork",
                        "name": spdx_license_list.LICENSES[
                            self.settings.run_license
                        ].name,
                    },
                )
            )
        else:
            self.wf_crate.license = self.settings.run_license