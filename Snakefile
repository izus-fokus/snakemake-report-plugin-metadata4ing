rule all:
    input:
        "hello.log",
        "goodbye.log"

rule say_hello:
    output:
        "hello.log"
    shell:
        "echo 'Hello from Snakemake!' > {output}"

rule say_goodbye:
    output:
        "goodbye.log"
    shell:
        "echo 'Goodbye from Snakemake!' > {output}"