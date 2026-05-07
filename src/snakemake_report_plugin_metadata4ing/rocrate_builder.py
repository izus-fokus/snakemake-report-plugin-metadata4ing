from rocrate.rocrate import ROCrate

from snakemake_report_plugin_metadata4ing.models import ProvenanceResult
from snakemake_report_plugin_metadata4ing.utils import get_mime_type


class Metadata4IngROCrateBuilder:
    def __init__(
        self,
        settings,
        config_data: dict,
        provenance_filename: str = "provenance.jsonld",
        provenance_ttl_filename: str = "provenance.ttl",
        ro_crate_version: str = "1.1",
    ):
        self.settings = settings
        self.config_data = config_data
        self.provenance_filename = provenance_filename
        self.provenance_ttl_filename = provenance_ttl_filename
        self.ro_crate_version = ro_crate_version
        self.crate = ROCrate(version=self.ro_crate_version)

    def write(self, provenance: ProvenanceResult) -> str:
        self._extend_rocrate_context(provenance.context_data)
        self._add_rocrate_config_data()

        if provenance.benchmark_processing_step_id:
            self.crate.mainEntity = {
                "@id": provenance.benchmark_processing_step_id.replace(
                    "local:", "#"
                )
            }

        self._add_supplemental_files(provenance)
        self._add_provenance_nodes_to_crate(provenance.jsonld)
        self._add_ro_crate_file_nodes(provenance.file_nodes)
        return self._create_ro_crate_file(provenance.simulation_hash)

    def _extend_rocrate_context(self, context_data: dict):
        metadata4ing_context = dict(context_data.get("@context", {}))
        metadata4ing_context.pop("@vocab", None)
        metadata4ing_context.pop("description", None)
        metadata4ing_context["softwareVersion"] = {"@id": "schema:softwareVersion"}
        metadata4ing_context["dataType"] = {"@id": "cr:dataType"}
        metadata4ing_context["extract"] = {"@id": "cr:extract"}
        metadata4ing_context["jsonPath"] = {"@id": "cr:jsonPath"}
        metadata4ing_context["schema"] = "http://schema.org/"
        self.crate.metadata.extra_contexts.append(metadata4ing_context)

    def _add_rocrate_config_data(self):
        rocrate_info = self.config_data.get("rocrate", {})
        self.crate.name = rocrate_info.get("name")
        self.crate.description = rocrate_info.get("description")
        self.crate.license = rocrate_info.get("license")

    def _add_supplemental_files(self, provenance: ProvenanceResult) -> None:
        for file in provenance.supplemental_files:
            self.crate.add_file(
                file.source_path,
                dest_path=file.dest_path,
                properties={
                    "name": file.name,
                    "encodingFormat": file.encoding_format,
                },
            )

    def _add_ro_crate_file_nodes(self, file_nodes: dict):
        self.crate.add_file(
            self.provenance_filename,
            dest_path=self.provenance_filename,
            properties={
                "name": self.provenance_filename,
                "encodingFormat": "application/ld+json",
                "conformsTo": [
                    f"https://w3id.org/ro/crate/{self.ro_crate_version}",
                    "https://w3id.org/nfdi4ing/metadata4ing/1.3.1",
                ],
            },
        )

        self.crate.add_file(
            self.provenance_ttl_filename,
            dest_path=self.provenance_ttl_filename,
            properties={
                "name": self.provenance_ttl_filename,
                "encodingFormat": "text/turtle",
            },
        )

        for file in file_nodes.keys():
            self.crate.add_file(
                file,
                dest_path=file,
                properties={
                    "name": file,
                    "encodingFormat": get_mime_type(file),
                },
            )

    def _create_ro_crate_file(self, simulation_hash: str) -> str:
        if self.settings.filename:
            crate_path = f"{self.settings.filename}.zip"
        else:
            crate_path = f"ro-crate-metadata-{simulation_hash}.zip"

        self.crate.write_zip(crate_path)
        return crate_path

    def _add_provenance_nodes_to_crate(self, jsonld) -> None:
        nodes = jsonld["@graph"]
        for node in nodes:
            entity_id = node["@id"]
            if entity_id is None or self.crate.get(entity_id):
                continue
            self.crate.add_jsonld(node)
