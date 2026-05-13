"""Graph-level provenance helpers."""

import hashlib
import json
from datetime import datetime

from rdflib import Graph, Namespace


class ProvenanceGraphHelpers:
    """Helpers that create graph-level nodes and relationships."""

    def _add_benchmark_processing_step(self, sorted_jobs) -> None:
        """Create the synthetic benchmark processing step spanning all jobs."""
        self.state.benchmark_processing_step_id = "local:processing_step_benchmark"
        earliest_start = min(item.starttime for item in sorted_jobs)
        latest_end = max(item.endtime for item in sorted_jobs)
        benchmark_node = {
            "@id": self.state.benchmark_processing_step_id,
            "@type": "processing step",
            "label": "benchmark",
            "start time": self._get_time_str(earliest_start),
            "end time": self._get_time_str(latest_end),
            "has input": [],
            "has output": [],
            "has parameter": [],
        }
        self.state.processing_steps[self.state.benchmark_processing_step_id] = benchmark_node

    def _add_precedes_relations(self, jsonld_data: dict) -> dict:
        """Infer ``precedes`` edges between processing steps."""
        g = Graph()
        g.parse(data=json.dumps(jsonld_data), format="json-ld")
        schema = Namespace("https://schema.org/")
        new_relations = []
        for a, _, f1 in g.triples((None, schema.result, None)):
            for b, _, f2 in g.triples((None, schema.object, None)):
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
            key = "precedes"
            existing = source_node.get(key)
            new_link = {"@id": f"local:{target_id}"}
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
        """Extract the local identifier component from an IRI."""
        local = iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if local.startswith("local:"):
            local = local.replace("local:", "")
        return local

    def _random_hash_from_json(self, json_content: dict, length=8) -> str:
        """Create a stable short hash from serialized JSON content."""
        json_str = json.dumps(json_content, sort_keys=True).encode("utf-8")
        hash_value = hashlib.sha256(json_str).hexdigest()
        return hash_value[:length]

    def _get_time_str(self, timestamp) -> str:
        """Convert a Unix timestamp into a local datetime string."""
        try:
            return f"{datetime.fromtimestamp(timestamp)}"
        except Exception:
            return ""
