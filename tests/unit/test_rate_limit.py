from core.rate_limit import RetryPolicy, call_with_retries


def test_retry_policy_succeeds_after_transient_errors():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("429 temporary rate limit")
        return "ok"

    value = call_with_retries(
        flaky,
        policy=RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.02, jitter=0.0),
    )
    assert value == "ok"
    assert attempts["count"] == 3

