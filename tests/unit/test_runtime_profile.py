from core.config import load_config


def test_balanced_profile_enables_distributed_and_storage():
    cfg = load_config({"runtime_profile": "balanced", "interactive_hitl": False})
    assert cfg.runtime_profile == "balanced"
    assert cfg.enable_distributed is True
    assert cfg.enable_storage is True
    assert cfg.enable_observability is False


def test_full_profile_enables_all_optional_subsystems():
    cfg = load_config({"runtime_profile": "full", "interactive_hitl": False})
    assert cfg.runtime_profile == "full"
    assert cfg.enable_distributed is True
    assert cfg.enable_storage is True
    assert cfg.enable_observability is True


def test_explicit_feature_override_wins_over_profile():
    cfg = load_config(
        {
            "runtime_profile": "full",
            "enable_distributed": False,
            "enable_observability": False,
            "interactive_hitl": False,
        }
    )
    assert cfg.runtime_profile == "full"
    assert cfg.enable_distributed is False
    assert cfg.enable_observability is False
    assert cfg.enable_storage is True

