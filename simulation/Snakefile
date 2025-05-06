from pathlib import Path

files = list(Path(".").rglob("parameters_*.json"))
names = [f.stem.split("_")[1] for f in files]

rule all:
    input:
        expand("summary_{name}.json", name=names),
        #expand("output_{name}.h5", name=names)

rule generate_input_files:
    input:
        "experiment.json",
        "parameters_{name}.json",
    output:
        "data/input_{name}.json",
        "data/mesh_{name}.msh",
    conda: "environment.yml"
    shell: "python3 create_input_files.py {wildcards.name} {input}"

rule run_simulation:
    input: 
        "data/input_{name}.json",
        "data/mesh_{name}.msh",
    output:
        "data/output_{name}.vtk",
    conda:
        "environment.yml",
    shell: "python3 run_simulation.py {wildcards.name} {input}"

rule summary:
    input:
        "data/output_{name}.vtk",
        "data/input_{name}.json",
        "data/mesh_{name}.msh",
        "parameters_{name}.json",
    output:
        "summary_{name}.json",
    run:
        import json
        summary = {}
        summary["name"] = wildcards.name
        summary["parameters"] = input[3]
        summary["input"] = input[1]
        summary["mesh"] = input[2]
        summary["output"] = input[0]
        with open(output[0], "w") as f:
            json.dump(summary, f, indent=4)