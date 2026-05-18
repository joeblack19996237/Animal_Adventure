import os

import pytest


@pytest.mark.live_e2e
@pytest.mark.skipif(
    os.environ.get("HARNESS_LIVE_E2E") != "1",
    reason="Live Claude smoke E2E is opt-in with HARNESS_LIVE_E2E=1",
)
def test_live_claude_minimal_fixture_completes():
    pytest.skip("Live smoke requires an interactive Claude CLI environment.")

