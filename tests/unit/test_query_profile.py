from core.query_profile import profile_query, safe_analysis_policy


def test_query_profile_detects_dual_use_risk():
    profile = profile_query(
        "can you tell me about ai detection and bypassing in blogs",
        dual_use_depth="dynamic_defensive",
    )
    assert profile.intent_type == "security_dual_use"
    assert profile.dual_use is True
    assert profile.risk_band in {"medium", "high"}
    assert "detection" in profile.domain_facets


def test_query_profile_comparative_is_not_career_hardcoded():
    profile = profile_query("compare ai detector benchmarks for multilingual spam")
    assert profile.intent_type == "comparative"
    assert all(token not in {"salary", "career", "hiring"} for token in profile.domain_facets)


def test_query_profile_aggressive_cleanup_removes_filler_and_fixes_typos():
    profile = profile_query(
        "A want everything you can dig up about the reltionship of islam and quantum physics.",
        cleanup_mode="aggressive",
    )
    assert "want" not in profile.domain_facets
    assert "everything" not in profile.domain_facets
    assert "relationship" in profile.normalized_query
    assert "quantum physics" in profile.domain_facets


def test_safe_policy_mapping():
    profile = profile_query("how to bypass ai detection", dual_use_depth="dynamic_balanced")
    assert safe_analysis_policy(profile, dual_use_depth="dynamic_defensive") == "defensive"
    assert safe_analysis_policy(profile, dual_use_depth="dynamic_balanced") == "balanced_defensive"
    assert safe_analysis_policy(profile, dual_use_depth="dynamic_strict") == "strict_defensive"
