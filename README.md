# Metadata4Ing Reporter For Snakemake

This project provides a Snakemake reporter plugin that exports workflow runs as
RO-Crates enriched with provenance derived from the
[Metadata4Ing ontology](https://nfdi4ing.pages.rwth-aachen.de/metadata4ing/metadata4ing/1.2.1/index.html).

The plugin:

- extracts provenance from executed Snakemake jobs
- serializes that provenance as `provenance.jsonld` and `provenance.ttl`
- packages the workflow run as an RO-Crate ZIP
- supports multiple RO-Crate profiles
- validates the generated crate automatically with [`rocrate_validator`](https://pypi.org/project/roc-validator/).

## Installation

Install directly from GitHub:

```bash
python -m pip install git+https://github.com/izus-fokus/snakemake-report-plugin-metadata4ing
```

Or build and install from source:

```bash
poetry build
python -m pip install --force-reinstall dist/snakemake_report_plugin_metadata4ing-2.0.0-py3-none-any.whl
```

After installation, the plugin is available as the `metadata4ing` Snakemake
reporter:

```bash
snakemake --reporter metadata4ing ...
```

## What The Reporter Produces

The reporter writes a single RO-Crate ZIP file. By default, the filename is:

```text
ro-crate-<simulation_hash>.zip
```

where `<simulation_hash>` is a deterministic hash derived from the generated
provenance graph.

The crate contains:

- `ro-crate-metadata.json`: RO-Crate metadata
- `provenance.jsonld`: provenance graph serialized as JSON-LD
- `provenance.ttl`: the same provenance graph serialized as Turtle
- workflow input, output, and supplemental files referenced by the run

After the crate is created, it is validated automatically against the selected
RO-Crate profile using [`rocrate_validator`](https://pypi.org/project/roc-validator/).

## Supported RO-Crate Profiles

The plugin currently supports these profiles:

- [`ro-crate-1.1`](https://www.researchobject.org/ro-crate/specification/1.1/).
- [`provenance-run-crate-0.5` ](https://www.researchobject.org/workflow-run-crate/profiles/provenance_run_crate/).

Use the `profile` reporter setting to choose which one to build:

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-profile ro-crate-1.1 \
  --cores 1
```

Or

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-profile provenance-run-crate-0.5 \
  --cores 1
```

### Profiles

# `ro-crate-1.1`

- produces a standard RO-Crate 1.1 archive
- copies the generated Metadata4Ing provenance graph into the crate as
  contextual entities
- keeps the provenance structure closest to the internal JSON-LD graph

# `provenance-run-crate-0.5`

- produces a workflow/provenance run crate
- derives workflow run entities such as actions, formal parameters, and
  software applications from the extracted provenance
- is useful when downstream tooling expects workflow run profile semantics

Both profiles use the same default filename pattern and both are validated
after creation.

## Reporter Parameters

### `profile`

Selects which RO-Crate profile is created.

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-profile provenance-run-crate-0.5 \
  --cores 1
```

### `filename`

Sets the output filename stem for the final crate ZIP. The `.zip` suffix is
added automatically.

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-filename my-report \
  --cores 1
```

This creates:

```text
my-report.zip
```

### `name`, `description`, and `license`

Set top-level RO-Crate metadata. Defaults are:

- `name`: `Snakemake Provenance Run`
- `description`: `RO-Crate describing a Snakemake workflow run.`
- `license`: `https://opensource.org/licenses/MIT`

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-name "NFDi4Ing Provenance" \
  --report-metadata4ing-description "Benchmark for linear-elastic plate with a hole" \
  --report-metadata4ing-license "https://opensource.org/licenses/MIT" \
  --cores 1
```

### `paramscript`

You can provide an external Python script that extracts parameters from input
or output files and turns them into provenance variables.

```bash
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-paramscript /path/to/my_extractor.py \
  --cores 1
```

The extractor must implement
[`ParameterExtractorInterface`](src/snakemake_report_plugin_metadata4ing/interfaces.py):

```python
class ParameterExtractorInterface(ABC):
    @abstractmethod
    def extract_params(self, rule_name: str, file_path: str) -> dict:
        ...
```

The `extract_params` method must return a dictionary of this shape:

```json
{
  "<processing-step-name>": {
    "has parameter": [
      {
        "<parameter-name>": {
          "value": 15,
          "unit": "m",
          "json-path": "/length/value",
          "data-type": "schema:Float"
        }
      }
    ],
    "investigates": [
      {
        "<result-name>": {
          "value": 1.0,
          "unit": "MPa",
          "json-path": "/max_mises_stress",
          "data-type": "schema:Float"
        }
      }
    ]
  }
}
```

Important details:

- top-level keys are processing-step names
- each processing-step value must be a dictionary
- `has parameter` and `investigates` must be lists
- each list item must be a one-entry dictionary
- each parameter entry must contain:
  - `value`
  - `unit`
  - `json-path`
  - `data-type`

Typical `data-type` values are:

- `schema:Text`
- `schema:Integer`
- `schema:Float`

If the extractor returns a different processing-step name from the current
Snakemake rule, the plugin treats that metadata as belonging to a derived step
under the same workflow run. This is useful when one file summarizes multiple
sub-results.

A sample extractor is included at
[`sample_extractor/my_extractor.py`](sample_extractor/my_extractor.py).

## Using The Examples

The repository contains runnable benchmark examples under:

- `examples/benchmarks/FEniCS`
- `examples/benchmarks/Kratos`

Each example contains:

- a `Snakefile`
- a `experiment.json`
- parameter JSON files
- simulation scripts

### Running The FEniCS Example

From the repository root:

```bash
cd examples/benchmarks/FEniCS
snakemake --cores 1 --software-deployment-method conda
```

To generate an RO-Crate with extracted parameter metadata:

```bash
cd examples/benchmarks/FEniCS
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-name "NFDi4Ing Provenance" \
  --report-metadata4ing-description "Benchmark for linear-elastic plate with a hole" \
  --report-metadata4ing-license "https://opensource.org/licenses/MIT" \
  --report-metadata4ing-paramscript ../../../sample_extractor/my_extractor.py \
  --report-metadata4ing-profile ro-crate-1.1 \
  --cores 1 \
  --software-deployment-method conda
```

To generate a provenance run crate instead:

```bash
cd examples/benchmarks/FEniCS
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-name "NFDi4Ing Provenance" \
  --report-metadata4ing-description "Benchmark for linear-elastic plate with a hole" \
  --report-metadata4ing-license "https://opensource.org/licenses/MIT" \
  --report-metadata4ing-paramscript ../../../sample_extractor/my_extractor.py \
  --report-metadata4ing-profile provenance-run-crate-0.5 \
  --cores 1 \
  --software-deployment-method conda
```

The example workflow will generate input files, run the simulation, build
summary JSON files, then emit a validated RO-Crate ZIP in the example
directory.

### Running The Kratos Example

The same reporter invocation pattern applies in `examples/benchmarks/Kratos`:

```bash
cd examples/benchmarks/Kratos
snakemake \
  --reporter metadata4ing \
  --report-metadata4ing-name "NFDi4Ing Provenance" \
  --report-metadata4ing-description "Benchmark for linear-elastic plate with a hole" \
  --report-metadata4ing-license "https://opensource.org/licenses/MIT" \
  --report-metadata4ing-paramscript ../../../sample_extractor/my_extractor.py \
  --report-metadata4ing-profile ro-crate-1.1 \
  --cores 1 \
  --software-deployment-method conda
```

An example generated crate is already checked into that directory as a sample
artifact.

## Notes

- The plugin validates the generated crate after writing it.
- Validation uses the same profile selected for crate generation.
- Supplemental files such as the Snakefile and referenced shell scripts are
  included in the crate when they are detected.
