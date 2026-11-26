PYTHON ?= python3.11

.PHONY: data test

data:
	$(PYTHON) -m src.extract.legal_corpus_builder
	$(PYTHON) -m src.extract.violation_extract
	$(PYTHON) -m src.reasoning.gen_auto_rules
	$(PYTHON) -m src.kg.build_kg
	$(PYTHON) -m src.kg.stats

test:
	$(PYTHON) -m pytest
