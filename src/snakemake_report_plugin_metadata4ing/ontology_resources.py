"""Lazy access to packaged ontology assets used during provenance extraction."""

import json
from importlib import resources

from pint import UnitRegistry
from rdflib import Graph

from snakemake_report_plugin_metadata4ing.jsonld import JsonLdDocument


class OntologyResources:
    """Lazy loader for packaged ontology assets and unit-mapping resources.

    The builder needs a JSON-LD context, a QUDT graph, and a small mapping
    between human-friendly unit strings and QUDT identifiers. This helper
    keeps those resources cached so repeated provenance builds do not reload
    the same package files over and over.
    """

    def __init__(self) -> None:
        """Initialize ontology-related caches and namespace constants.

        Returns:
            None.
        """
        self.context_data: JsonLdDocument | None = None
        self.unit_graph = Graph()
        self._qudt_loaded = False
        self._qudt_mapping: dict[str, str] | None = None
        self.qudt_url = "http://qudt.org/schema/qudt/"
        self.unit_url = "http://qudt.org/vocab/unit/"
        self.mardi4nfdi_url = "https://mardi4nfdi.de/mathmoddb#"
        self.ureg = UnitRegistry()

    def load_context(self) -> JsonLdDocument:
        """Load the packaged Metadata4Ing JSON-LD context.

        Returns:
            JsonLdDocument: Parsed JSON-LD context document loaded from the
            packaged ``metadata4ing.jsonld`` resource. The same object is
            reused on later calls.
        """
        if self.context_data is None:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("metadata4ing.jsonld").open("r", encoding="utf-8") as handle:
                self.context_data = json.load(handle)
        return self.context_data

    def load_qudt_graph(self) -> Graph:
        """Load the packaged QUDT ontology graph.

        Returns:
            Graph: RDF graph parsed from the packaged ``qudt.ttl`` file. The
            graph is cached after the first call.
        """
        if not self._qudt_loaded:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("qudt.ttl").open("r", encoding="utf-8") as handle:
                self.unit_graph.parse(data=handle.read(), format="ttl")
            self._qudt_loaded = True
        return self.unit_graph

    def get_qudt_unit(self, unit: str) -> str | None:
        """Resolve a free-form unit string to a QUDT unit identifier.

        Args:
            unit: Unit expression returned by the parameter extractor, such as
                ``m/s`` or ``second``.

        Returns:
            str | None: A QUDT-prefixed identifier such as ``unit:M`` when the
            mapping is known. If the unit parses but is not in the mapping, the
            original string is returned so the caller can still preserve it.
        """
        if self._qudt_mapping is None:
            with resources.files(
                "snakemake_report_plugin_metadata4ing.ontologies"
            ).joinpath("qudt-mapping.json").open("r", encoding="utf-8") as handle:
                self._qudt_mapping = json.load(handle)
        pint_unit = self.ureg.parse_units(unit)
        if str(pint_unit) in self._qudt_mapping:
            return f"unit:{self._qudt_mapping[str(pint_unit)]}"
        return unit
