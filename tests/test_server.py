"""Test cho dashboard server"""

import pytest
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_import_server():
    """Server module import được"""
    import server

    assert server is not None


def test_get_metrics():
    """Hàm get_metrics trả về dict với các key cần thiết"""
    from server import get_metrics

    data = get_metrics()
    assert isinstance(data, dict)
    assert "cpu" in data
    assert "memory" in data
    assert "disk" in data
    assert "network" in data


def test_metrics_values():
    """Metrics có giá trị hợp lệ"""
    from server import get_metrics

    data = get_metrics()
    assert 0 <= data["cpu"]["percent"] <= 100
    assert 0 <= data["memory"]["percent"] <= 100
