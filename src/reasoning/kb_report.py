#!/usr/bin/env python3
"""
Knowledge Base Report Generator for Phase P1a
Prints statistics and exports verify_sheet.csv
"""

import yaml
import csv
from pathlib import Path
from typing import Dict, List


KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "data" / "knowledge"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "knowledge"


def load_yaml(filepath: Path) -> dict:
    """Load a YAML file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def count_verified(items: List[dict]) -> tuple:
    """Count verified and unverified items"""
    verified = sum(1 for item in items if item.get("verified", False))
    unverified = len(items) - verified
    return verified, unverified


def generate_report():
    """Generate knowledge base report"""
    print("=" * 80)
    print("KNOWLEDGE BASE REPORT - Phase P1a")
    print("=" * 80)
    print()

    # Ontology
    print("## ONTOLOGY")
    ontology = load_yaml(KNOWLEDGE_DIR / "ontology.yaml")
    
    print(f"  Vehicle Classes: {len(ontology['vehicle_classes'])}")
    print(f"  Road Types: {len(ontology['road_types'])}")
    print(f"  Time Contexts: {len(ontology['time_contexts'])}")
    print(f"  Alcohol Levels: {len(ontology['alcohol_levels'])}")
    print(f"  Speed Bands: {len(ontology['speed_bands'])}")
    print(f"  Consequences: {len(ontology['consequences'])}")
    print(f"  Resistance Behaviors: {len(ontology['resistance_behaviors'])}")
    print(f"  Subjects: {len(ontology['subjects'])}")
    print(f"  Additional Sanction Types: {len(ontology['additional_sanction_types'])}")
    print()

    # Acts
    print("## ACTS")
    acts_data = load_yaml(KNOWLEDGE_DIR / "acts.yaml")
    acts = acts_data["acts"]
    verified, unverified = count_verified(acts)
    print(f"  Total Acts: {len(acts)}")
    print(f"    Verified: {verified}")
    print(f"    Unverified: {unverified}")
    
    core_acts = ["ACT_RED_LIGHT", "ACT_ALCOHOL", "ACT_SPEEDING", 
                 "ACT_NO_HELMET", "ACT_PASSENGER_NO_HELMET", "ACT_IGNORE_OFFICER"]
    print(f"  Core Acts (6 nhóm làm sâu): {sum(1 for a in acts if a['id'] in core_acts)}")
    print()

    # Circumstances
    print("## CIRCUMSTANCES")
    circs_data = load_yaml(KNOWLEDGE_DIR / "circumstances.yaml")
    
    mitigating = circs_data["mitigating_circumstances"]
    aggravating = circs_data["aggravating_circumstances"]
    
    mit_verified, mit_unverified = count_verified(mitigating)
    agg_verified, agg_unverified = count_verified(aggravating)
    
    print(f"  Mitigating Circumstances: {len(mitigating)}")
    print(f"    Verified: {mit_verified}")
    print(f"    Unverified: {mit_unverified}")
    print(f"  Aggravating Circumstances: {len(aggravating)}")
    print(f"    Verified: {agg_verified}")
    print(f"    Unverified: {agg_unverified}")
    print()

    # Rules
    print("## RULES")
    
    rule_files = {
        "derive.yaml": "Derive",
        "classify_core.yaml": "Classify Core",
        "classify_auto.yaml": "Classify Auto",
        "escalate.yaml": "Escalate",
        "ask.yaml": "Ask",
        "temporal.yaml": "Temporal",
        "note.yaml": "Note"
    }
    
    all_rules = []
    total_verified = 0
    total_unverified = 0
    
    for filename, rule_type in rule_files.items():
        filepath = KNOWLEDGE_DIR / "rules" / filename
        if filepath.exists():
            rules_data = load_yaml(filepath)
            rules = rules_data.get("rules", [])
            verified, unverified = count_verified(rules)
            
            print(f"  {rule_type}: {len(rules)}")
            print(f"    Verified: {verified}")
            print(f"    Unverified: {unverified}")
            
            total_verified += verified
            total_unverified += unverified
            
            # Collect for CSV (machine-generated rules need no manual review)
            for rule in [] if filename == "classify_auto.yaml" else rules:
                all_rules.append({
                    "rule_id": rule["id"],
                    "type": rule.get("type", ""),
                    "when": str(rule.get("when", {})),
                    "then": str(rule.get("then", {})),
                    "citation_id": extract_citation_id(rule),
                    "legal_excerpt": rule.get("legal_excerpt", ""),
                    "verified": rule.get("verified", False)
                })
    
    print()
    print(f"  TOTAL RULES: {total_verified + total_unverified}")
    print(f"    Verified: {total_verified}")
    print(f"    Unverified: {total_unverified}")
    print()

    # Export verify sheet
    print("## EXPORT")
    csv_path = OUTPUT_DIR / "verify_sheet.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "rule_id", "type", "when", "then", "citation_id", "legal_excerpt", "verified"
        ])
        writer.writeheader()
        writer.writerows(all_rules)
    
    print(f"  Exported verify_sheet.csv to: {csv_path}")
    print(f"  Total rules exported: {len(all_rules)}")
    print()
    
    print("=" * 80)
    print("Report completed successfully!")
    print("=" * 80)


def extract_citation_id(rule: dict) -> str:
    """Extract citation_id from rule"""
    # Try direct citation_id field
    if "citation_id" in rule:
        return rule["citation_id"]
    
    # Try source field
    source = rule.get("source", "")
    if "ND168" in source or "NĐ 168" in source:
        return source
    
    # Try then clause
    then = rule.get("then", {})
    if "add_violation" in then:
        return then["add_violation"]
    if "escalate_to" in then:
        return then["escalate_to"]
    
    # Try has_violation in when
    when = rule.get("when", {})
    if "has_violation" in when:
        violations = when["has_violation"]
        if isinstance(violations, list) and violations:
            return ", ".join(violations)
        return str(violations)
    
    return ""


if __name__ == "__main__":
    generate_report()
