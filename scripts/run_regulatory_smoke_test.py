from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from general_claims import build_general_claim_plan
from policy_router import assess_case_payload, classify_case_payload

CASES = [
    ("data/test_flight_delay_2h_not_eligible.json", "flight", False),
    ("data/test_rail_delay.json", "rail", True),
    ("data/test_bus_cancellation.json", "bus_coach", True),
    ("data/test_ferry_delay.json", "sea", True),
    ("data/test_parcel_not_delivered.json", "parcel_delivery", True),
    ("data/test_package_travel_cancelled.json", "package_travel", True),
]


def main() -> int:
    failures = []
    print("== Regulatory Smoke Test ==")
    for rel_path, expected_case, expected_eligible in CASES:
        path = ROOT / rel_path
        payload = json.loads(path.read_text(encoding="utf-8"))
        cls = classify_case_payload(payload)
        assessment = assess_case_payload(payload, case_type_override=cls.get("case_type"))
        plan = build_general_claim_plan(payload, assessment)

        got_case = plan.get("case_type")
        got_eligible = bool((plan.get("eligibility") or {}).get("eligible"))
        citation_ok = bool(plan.get("citation_requirement_met"))
        article_refs = plan.get("article_references") or []

        ok = got_case == expected_case and got_eligible == expected_eligible and citation_ok
        status = "PASS" if ok else "FAIL"

        print(f"[{status}] {rel_path}")
        print(f"  classified_case={got_case} expected_case={expected_case}")
        print(f"  eligible={got_eligible} expected_eligible={expected_eligible}")
        print(f"  citation_requirement_met={citation_ok}")
        print(f"  article_references={article_refs}")

        if not ok:
            failures.append(rel_path)

    if failures:
        print("\nFAILED CASES:")
        for f in failures:
            print(f"- {f}")
        return 1

    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
