.PHONY: check core-check ns3-conformance runtime-benchmark runtime-benchmark-trials framework-tables program-functions-check program-functions-analysis

PAPER_TABLE_DIR ?= paper/generated
PROGRAM_FUNCTION_DIR ?=

check:
	python3 scripts/validate_artifact.py
	python3 scripts/generate_framework_evaluation_tables.py --check-only
	python3 ns3/contrib/information-routing/utils/analyze_program_functions.py --check-config

core-check:
	bash scripts/test_portable_core.sh

ns3-conformance:
	bash scripts/test_ns3_conformance.sh

runtime-benchmark:
	bash scripts/run_runtime_benchmark.sh

runtime-benchmark-trials:
	bash scripts/run_runtime_benchmark_trials.sh

framework-tables:
	python3 scripts/generate_framework_evaluation_tables.py --output-dir "$(PAPER_TABLE_DIR)"

program-functions-check:
	python3 ns3/contrib/information-routing/utils/analyze_program_functions.py --check-config

program-functions-analysis:
	test -n "$(PROGRAM_FUNCTION_DIR)"
	python3 ns3/contrib/information-routing/utils/analyze_program_functions.py --input-dir "$(PROGRAM_FUNCTION_DIR)"
