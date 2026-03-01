from core.models import QueryProfile
from core.verification import query_requires_open_availability


def _profile(constraints: dict[str, str] | None = None) -> QueryProfile:
    return QueryProfile(
        original_query="",
        normalized_query="",
        typed_constraints=constraints or {},
    )


def test_open_availability_intent_triggered_non_opportunity_query_is_not_forced():
    profile = _profile()
    assert (
        query_requires_open_availability(
            profile,
            availability_policy="must_be_open",
            availability_enforcement_scope="intent_triggered",
            opportunity_query_detection="auto",
            query="Compare AI detector methods for long-form blogs and false positives.",
        )
        is False
    )


def test_open_availability_intent_triggered_opportunity_query_is_enforced():
    profile = _profile()
    assert (
        query_requires_open_availability(
            profile,
            availability_policy="must_be_open",
            availability_enforcement_scope="intent_triggered",
            opportunity_query_detection="auto",
            query="Find currently available fully funded AI master's scholarships with open applications.",
        )
        is True
    )


def test_open_availability_always_scope_enforces_when_policy_requires_it():
    profile = _profile()
    assert (
        query_requires_open_availability(
            profile,
            availability_policy="must_be_open",
            availability_enforcement_scope="always",
            opportunity_query_detection="off",
            query="Any technical query text.",
        )
        is True
    )
