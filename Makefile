PYTHON ?= python3.11

.PHONY: data test eval-validate eval-smoke eval-local

data:
	$(PYTHON) -m src.extract.legal_corpus_builder
	$(PYTHON) -m src.extract.violation_extract
	$(PYTHON) -m src.reasoning.gen_auto_rules
	$(PYTHON) -m src.kg.build_kg
	$(PYTHON) -m src.kg.stats

test:
	$(PYTHON) -m pytest

eval-validate:
	$(PYTHON) scripts/validate_cases.py

# Smoke results go to their own folder so they never mix with data/eval/results.
eval-smoke:
	$(PYTHON) -m src.eval.run_eval --cases data/eval/smoke_cases.jsonl \
		--config oracle_facts regex_extractor --out data/eval/smoke_results

eval-local:
	$(PYTHON) -m src.eval.run_eval --cases data/eval/test_cases.jsonl \
		--config oracle_facts regex_extractor
