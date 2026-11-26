"""
Test knowledge files for Phase P1a
Validates:
- YAML hợp lệ theo Pydantic schema
- Mọi citation_id trong rules tồn tại trong law_corpus (sẽ check sau khi có corpus)
- Mọi act/circumstance/enum ID tham chiếu đều được định nghĩa
- Không trùng id
"""

import pytest
import yaml
from pathlib import Path
from typing import Dict, List, Set

KNOWLEDGE_DIR = Path(__file__).parent.parent / "data" / "knowledge"


def load_yaml(filepath: Path) -> dict:
    """Load a YAML file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


class TestOntology:
    def test_ontology_loads(self):
        """Test that ontology.yaml loads correctly"""
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        assert ontology is not None
        assert "vehicle_classes" in ontology
        assert "alcohol_levels" in ontology
        assert "speed_bands" in ontology
        assert "consequences" in ontology
        assert "resistance_behaviors" in ontology
        assert "subjects" in ontology

    def test_vehicle_class_ids_unique(self):
        """Test that vehicle class IDs are unique"""
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        ids = [vc["id"] for vc in ontology["vehicle_classes"]]
        assert len(ids) == len(set(ids)), "Duplicate vehicle class IDs found"

    def test_vehicle_class_hierarchy(self):
        """Test that vehicle class hierarchy is valid"""
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        ids = {vc["id"] for vc in ontology["vehicle_classes"]}
        
        for vc in ontology["vehicle_classes"]:
            parent = vc.get("parent")
            if parent is not None:
                assert parent in ids, f"Parent {parent} not found for {vc['id']}"

    def test_alcohol_levels(self):
        """Test that alcohol levels are defined correctly"""
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        levels = ontology["alcohol_levels"]
        
        assert len(levels) == 3, "Should have 3 alcohol levels"
        
        level_ids = [l["id"] for l in levels]
        assert "BAC_L1" in level_ids
        assert "BAC_L2" in level_ids
        assert "BAC_L3" in level_ids

    def test_speed_bands(self):
        """Test that speed bands are defined correctly"""
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        bands = ontology["speed_bands"]
        
        assert len(bands) >= 4, "Should have at least 4 speed bands"
        
        band_ids = [b["id"] for b in bands]
        assert "SPEED_5_10" in band_ids
        assert "SPEED_10_20" in band_ids
        assert "SPEED_20_35" in band_ids
        assert "SPEED_OVER_35" in band_ids


class TestActs:
    def test_acts_loads(self):
        """Test that acts.yaml loads correctly"""
        acts = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        assert acts is not None
        assert "acts" in acts

    def test_act_ids_unique(self):
        """Test that act IDs are unique"""
        acts = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        ids = [a["id"] for a in acts["acts"]]
        assert len(ids) == len(set(ids)), "Duplicate act IDs found"

    def test_core_acts_present(self):
        """Test that 6 core acts are present"""
        acts = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        act_ids = {a["id"] for a in acts["acts"]}
        
        core_acts = {
            "ACT_RED_LIGHT",
            "ACT_ALCOHOL",
            "ACT_SPEEDING",
            "ACT_NO_HELMET",
            "ACT_PASSENGER_NO_HELMET",
            "ACT_IGNORE_OFFICER"
        }
        
        for core_act in core_acts:
            assert core_act in act_ids, f"Core act {core_act} not found"

    def test_acts_have_synonyms(self):
        """Test that each act has at least 6 synonyms"""
        acts = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        
        for act in acts["acts"]:
            synonyms = act.get("synonyms", [])
            assert len(synonyms) >= 6, f"Act {act['id']} has less than 6 synonyms"


class TestCircumstances:
    def test_circumstances_loads(self):
        """Test that circumstances.yaml loads correctly"""
        circs = load_yaml(KNOWLEDGE_DIR / "circumstances.yaml")
        assert circs is not None
        assert "mitigating_circumstances" in circs
        assert "aggravating_circumstances" in circs

    def test_circumstance_ids_unique(self):
        """Test that circumstance IDs are unique"""
        circs = load_yaml(KNOWLEDGE_DIR / "circumstances.yaml")
        
        all_circs = circs["mitigating_circumstances"] + circs["aggravating_circumstances"]
        ids = [c["id"] for c in all_circs]
        assert len(ids) == len(set(ids)), "Duplicate circumstance IDs found"

    def test_key_circumstances_present(self):
        """Test that key circumstances are present"""
        circs = load_yaml(KNOWLEDGE_DIR / "circumstances.yaml")
        
        agg_ids = {c["id"] for c in circs["aggravating_circumstances"]}
        mit_ids = {c["id"] for c in circs["mitigating_circumstances"]}
        
        # Key aggravating circumstances
        assert "CIR_REPEAT" in agg_ids
        assert "CIR_INSULT_OFFICER" in agg_ids
        assert "CIR_CONTINUE_AFTER_STOP" in agg_ids
        assert "CIR_CONCEAL" in agg_ids
        
        # Key mitigating circumstances
        assert "CIR_VOLUNTARY_CONFESS" in mit_ids
        assert "CIR_PREVENT_HARM" in mit_ids
        assert "CIR_HARDSHIP" in mit_ids


class TestRules:
    def test_derive_rules_load(self):
        """Test that derive.yaml loads correctly"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "derive.yaml")
        assert rules is not None
        assert "rules" in rules
        assert len(rules["rules"]) >= 15, "Should have at least 15 derive rules"

    def test_classify_core_loads(self):
        """Test that classify_core.yaml loads correctly"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "classify_core.yaml")
        assert rules is not None
        assert "rules" in rules

    def test_escalate_loads(self):
        """Test that escalate.yaml loads correctly"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "escalate.yaml")
        assert rules is not None
        assert "rules" in rules

    def test_ask_loads(self):
        """Test that ask.yaml loads correctly"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "ask.yaml")
        assert rules is not None
        assert "rules" in rules

    def test_temporal_loads(self):
        """Test that temporal.yaml loads correctly"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "temporal.yaml")
        assert rules is not None
        assert "rules" in rules

    def test_rule_ids_unique(self):
        """Test that rule IDs are unique across all rule files"""
        rule_files = [
            "derive.yaml",
            "classify_core.yaml",
            "escalate.yaml",
            "ask.yaml",
            "temporal.yaml",
            "note.yaml"
        ]
        
        all_ids = []
        for filename in rule_files:
            filepath = KNOWLEDGE_DIR / "rules" / filename
            if filepath.exists():
                rules = load_yaml(filepath)
                for rule in rules.get("rules", []):
                    all_ids.append((rule["id"], filename))
        
        ids_only = [id for id, _ in all_ids]
        assert len(ids_only) == len(set(ids_only)), f"Duplicate rule IDs found: {[id for id, file in all_ids if ids_only.count(id) > 1]}"

    def test_classify_rules_reference_valid_acts(self):
        """Test that classify rules reference valid acts"""
        # Load acts
        acts_data = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        valid_acts = {a["id"] for a in acts_data["acts"]}
        
        # Load classify rules
        classify = load_yaml(KNOWLEDGE_DIR / "rules" / "classify_core.yaml")
        
        for rule in classify["rules"]:
            when = rule.get("when", {})
            if "has_act" in when:
                act_id = when["has_act"]
                assert act_id in valid_acts, f"Rule {rule['id']} references unknown act {act_id}"


    def test_note_loads(self):
        """Test that note.yaml loads and only contains note rules"""
        rules = load_yaml(KNOWLEDGE_DIR / "rules" / "note.yaml")
        assert rules["rules"]
        assert all(r["type"] == "note" for r in rules["rules"])

    def test_all_rules_validate_against_schema(self):
        """Every rule validates against the Pydantic Rule schema (types + operators)"""
        from src.reasoning.knowledge_base import KnowledgeBase

        kb = KnowledgeBase.load(corpus_path=None)
        assert len(kb.rules) > 0


class TestLegalExcerpts:
    @staticmethod
    def _corpus_body(citation_id: str) -> str:
        import json
        import re

        corpus = Path(__file__).parent.parent / "data" / "structured" / "law_corpus.jsonl"
        with open(corpus, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row["citation_id"] == citation_id:
                    body = row["text"].split("\n", 1)[1]
                    return re.sub(r"^(\d+\.|[a-zđ]\))\s*", "", body).strip()
        raise AssertionError(f"{citation_id} not in law_corpus.jsonl")

    @pytest.mark.parametrize(
        "rule_id,citation_id",
        [("R-CLS-HITRUN-CAR", "ND168-D6-K8"), ("R-CLS-HITRUN-MOTO", "ND168-D7-K9-Pc")],
    )
    def test_hit_and_run_excerpt_is_verbatim(self, rule_id, citation_id):
        classify = load_yaml(KNOWLEDGE_DIR / "rules" / "classify_core.yaml")
        rule = next(r for r in classify["rules"] if r["id"] == rule_id)
        assert rule["then"]["add_violation"] == citation_id
        assert rule["legal_excerpt"] == self._corpus_body(citation_id)

    def test_khoan_level_violation_present(self):
        import json

        path = Path(__file__).parent.parent / "data" / "structured" / "violations_168_clean.json"
        ids = {v["citation_id"] for v in json.loads(path.read_text(encoding="utf-8"))}
        assert "ND168-D6-K8" in ids
        assert "ND168-D7-K9-Pc" in ids


class TestCrossReferences:
    def test_derive_rules_reference_valid_contexts(self):
        """Test that derive rules add valid contexts"""
        # Load ontology
        ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
        
        valid_speed_bands = {b["id"] for b in ontology["speed_bands"]}
        valid_alcohol_levels = {l["id"] for l in ontology["alcohol_levels"]}
        valid_contexts = valid_speed_bands | valid_alcohol_levels
        
        # Load derive rules
        derive = load_yaml(KNOWLEDGE_DIR / "rules" / "derive.yaml")
        
        for rule in derive["rules"]:
            then = rule.get("then", {})
            if "add_context" in then:
                contexts = then["add_context"]
                if isinstance(contexts, str):
                    contexts = [contexts]
                for ctx in contexts:
                    assert ctx in valid_contexts, f"Rule {rule['id']} adds unknown context {ctx}"

    def test_derive_rules_reference_valid_acts(self):
        """Test that derive rules add valid acts"""
        # Load acts
        acts_data = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
        valid_acts = {a["id"] for a in acts_data["acts"]}
        
        # Load derive rules
        derive = load_yaml(KNOWLEDGE_DIR / "rules" / "derive.yaml")
        
        for rule in derive["rules"]:
            then = rule.get("then", {})
            if "add_acts" in then:
                acts = then["add_acts"]
                if isinstance(acts, str):
                    acts = [acts]
                for act in acts:
                    assert act in valid_acts, f"Rule {rule['id']} adds unknown act {act}"

    def test_derive_rules_reference_valid_circumstances(self):
        """Test that derive rules add valid circumstances"""
        # Load circumstances
        circs_data = load_yaml(KNOWLEDGE_DIR / "circumstances.yaml")
        all_circs = circs_data["mitigating_circumstances"] + circs_data["aggravating_circumstances"]
        valid_circs = {c["id"] for c in all_circs}
        
        # Load derive rules
        derive = load_yaml(KNOWLEDGE_DIR / "rules" / "derive.yaml")
        
        for rule in derive["rules"]:
            then = rule.get("then", {})
            if "add_circumstances" in then:
                circs = then["add_circumstances"]
                if isinstance(circs, str):
                    circs = [circs]
                for circ in circs:
                    assert circ in valid_circs, f"Rule {rule['id']} adds unknown circumstance {circ}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
