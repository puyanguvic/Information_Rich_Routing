.PHONY: check core-check candidate-fib-study candidate-fib-figure ns3-conformance srlinux-adapter srlinux-conformance runtime-benchmark runtime-benchmark-trials framework-tables program-functions-check program-functions-analysis

PAPER_TABLE_DIR ?= paper/generated
PROGRAM_FUNCTION_DIR ?=
SRLINUX_ADAPTER_BUILD_DIR ?= build/srlinux-adapter

check:
	python3 scripts/validate_artifact.py
	python3 scripts/generate_framework_evaluation_tables.py --check-only
	python3 ns3/contrib/information-routing/utils/analyze_program_functions.py --check-config

core-check:
	bash scripts/test_portable_core.sh

candidate-fib-study:
	python3 scripts/analyze_candidate_fib.py --output-dir results/candidate-fib-study

candidate-fib-figure: candidate-fib-study
	python3 paper/figure-scripts/draw_candidate_fib_study.py

ns3-conformance:
	bash scripts/test_ns3_conformance.sh

srlinux-adapter:
	cmake -S containerlab/srlinux-clos2x2/adapter -B "$(SRLINUX_ADAPTER_BUILD_DIR)" -DCMAKE_BUILD_TYPE=Release
	cmake --build "$(SRLINUX_ADAPTER_BUILD_DIR)" --parallel --target ir-srlinux-c-api

srlinux-conformance:
	bash scripts/test_srlinux_conformance.sh

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
