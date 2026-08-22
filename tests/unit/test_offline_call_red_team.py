import asyncio
from collections import Counter

from agent.eval.offline_call_red_team import build_cases, run_campaign


def test_offline_call_red_team_has_over_one_thousand_unique_cases():
    cases = build_cases()
    assert len(cases) >= 1000
    assert len({case.case_id for case in cases}) == len(cases)
    semantic_scenarios = {
        (case.language, case.caller_input, case.injected_agent_output, case.expected)
        for case in cases
    }
    assert len(semantic_scenarios) >= 1000
    categories = Counter(case.category for case in cases)
    assert len(categories) >= 15
    assert all(count > 0 for count in categories.values())


def test_every_offline_call_red_team_case_passes():
    results = asyncio.run(run_campaign())
    failures = [
        f"{result.case_id}: {'; '.join(result.defects)} => {result.observed}"
        for result in results
        if not result.passed
    ]
    assert not failures, "\n" + "\n".join(failures[:100])
