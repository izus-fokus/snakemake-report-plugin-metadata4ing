rule all:
    input:
        "hello.log",
        "goodbye.log",
        "prepare.log",
        "cleanup.log"

rule prepare:
    output:
        "prepare.log"
    shell:
        "echo 'Preparing workflow...' > {output}"

rule say_hello:
    input:
        "prepare.log"
    output:
        "hello.log"
    shell:
        "echo 'Hello from Snakemake!' > {output}"

rule say_goodbye:
    input:
        "hello.log"
    output:
        "goodbye.log"
    shell:
        "echo 'Goodbye from Snakemake!' > {output}"

rule cleanup:
    input:
        "goodbye.log"
    output:
        "cleanup.log"
    shell:
        "echo 'Cleaning up after workflow...' > {output}"
