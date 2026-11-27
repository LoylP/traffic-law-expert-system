"""OWL export (no Java needed: the reasoner is exercised by `make owl`)."""

import pytest
from owlready2 import World

from src.extract.legal_corpus_builder import canonical_citation_id
from src.kg.build_kg import LAW_CORPUS_FILE, load_jsonl
from src.kg.export_owl import DEFINED_CLASSES, count_from_kb, count_from_kg, export_owl


@pytest.fixture(scope="module")
def onto(tmp_path_factory):
    path = tmp_path_factory.mktemp("owl") / "traffic.owl"
    export_owl(path)
    return World().get_ontology(path.as_uri()).load()


def test_reloaded_file_has_all_violations(onto):
    violations = onto["Violation"].instances()
    assert len(violations) == 634
    assert all(len(v.basedOn) == 1 for v in violations)


def test_defined_classes_have_no_asserted_members(onto):
    for spec in DEFINED_CLASSES:
        assert onto[spec.name].equivalent_to, spec.name
        assert not onto[spec.name].instances(), spec.name


def test_legal_excerpts_are_verbatim_corpus_text(onto):
    corpus: dict[str, set[str]] = {}
    for row in load_jsonl(LAW_CORPUS_FILE):
        corpus.setdefault(canonical_citation_id(row["citation_id"]), set()).add(row["text"])
    for provision in onto["LegalProvision"].instances():
        assert provision.legalExcerpt[0] in corpus[provision.name], provision.name
    for violation in onto["Violation"].instances():
        assert violation.legalExcerpt[0] in corpus[violation.basedOn[0].name], violation.name


def test_kg_and_kb_direct_counts_agree():
    kg, kb = count_from_kg(), count_from_kb()
    assert kg == kb
    assert all(kg[spec.name] for spec in DEFINED_CLASSES)
