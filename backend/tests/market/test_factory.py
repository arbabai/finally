import os
import pytest
from unittest.mock import patch

from app.market.factory import create_market_source
from app.market.simulator import MarketSimulator
from app.market.massive_client import MassiveClient


def test_no_api_key_returns_simulator():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("MASSIVE_API_KEY", None)
        source = create_market_source()
    assert isinstance(source, MarketSimulator)


def test_empty_api_key_returns_simulator():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": ""}):
        source = create_market_source()
    assert isinstance(source, MarketSimulator)


def test_whitespace_api_key_returns_simulator():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "   "}):
        source = create_market_source()
    assert isinstance(source, MarketSimulator)


def test_api_key_returns_massive_client():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key-123"}):
        source = create_market_source()
    assert isinstance(source, MassiveClient)


def test_massive_client_gets_api_key():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "my-secret-key"}):
        source = create_market_source()
    assert isinstance(source, MassiveClient)
    assert source._api_key == "my-secret-key"


def test_massive_client_default_poll_interval():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}):
        os.environ.pop("MASSIVE_POLL_INTERVAL", None)
        source = create_market_source()
    assert isinstance(source, MassiveClient)
    assert source._poll_interval == 15.0


def test_massive_client_custom_poll_interval():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key", "MASSIVE_POLL_INTERVAL": "5.0"}):
        source = create_market_source()
    assert isinstance(source, MassiveClient)
    assert source._poll_interval == 5.0


def test_simulator_source_name():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("MASSIVE_API_KEY", None)
        source = create_market_source()
    assert source.source_name == "Simulator"


def test_massive_client_source_name():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}):
        source = create_market_source()
    assert source.source_name == "MassiveAPI"
