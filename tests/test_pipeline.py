from unittest.mock import MagicMock, patch
from orchestrator import WiredOrchestrator


def test_imports():
    assert WiredOrchestrator is not None


def test_init():
    # Professionally mocking the DataEngine instantiation to ensure orchestration unit tests
    # run cleanly without physical environment dependencies.
    with patch('data.data_engine.DataEngine') as mock_engine:
        orch = WiredOrchestrator(mode="BACKTEST")
        assert orch.mode == "BACKTEST"
        assert orch.scanner is not None
        assert orch.tracker is not None
