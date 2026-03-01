from agents.planner import generate_subtopics


def test_generate_subtopics_falls_back_without_supported_provider():
    subtopics = generate_subtopics(
        "Compare detector robustness and false positives in long-form AI blogs",
        client=None,
        provider="unsupported",
        model="none",
        count=3,
        max_count=4,
    )
    assert len(subtopics) == 3
    assert all(item.sub_query for item in subtopics)
    assert all(item.id.startswith("S") for item in subtopics)

