"""Phase 4 unit tests — always use MockMT5Gateway (never real order_send)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppSettings, reset_settings_cache
from app.mt5.client import MT5Client, MT5Error
from app.mt5.gateway import MockMT5Gateway, MockSymbol
from app.mt5.models import SymbolTradeMode
from app.mt5.pricing import MT5PricingService
from app.mt5.service import MT5Service
from app.mt5.symbols import MT5SymbolService


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    return AppSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        symbol_mappings={"XAUUSD": "XAUUSDm", "GOLD": "XAUUSDm", "EURUSD": "EURUSD"},
    )


@pytest.fixture
def mock_gw() -> MockMT5Gateway:
    return MockMT5Gateway()


@pytest.fixture
def service(settings: AppSettings, mock_gw: MockMT5Gateway) -> MT5Service:
    return MT5Service(settings, gateway=mock_gw)


class TestMT5Client:
    def test_connect_and_account(self, service: MT5Service) -> None:
        account = service.connect()
        assert service.is_connected
        assert account.login == 12345678
        assert account.server == "Mock-Server"
        assert account.balance == 10000.0
        assert account.equity == 10050.0
        assert account.trade_allowed is True
        terminal = service.client.get_terminal_info()
        assert terminal is not None
        assert terminal.connected is True
        service.disconnect()
        assert not service.is_connected

    def test_connect_failure(self, settings: AppSettings) -> None:
        gw = MockMT5Gateway()
        gw.init_fail = True
        client = MT5Client(settings, gateway=gw)
        with pytest.raises(MT5Error, match="initialize failed"):
            client.connect()
        assert client.status.value == "unavailable"


class TestSymbolService:
    def test_map_and_validate_xauusd(self, service: MT5Service) -> None:
        service.connect()
        result = service.validate_symbol("XAUUSD", direction="SELL")
        assert result.ok is True
        assert result.mt5_symbol == "XAUUSDm"
        assert result.spec is not None
        assert result.spec.point == 0.01
        assert result.spec.digits == 2
        assert result.spec.trade_mode == SymbolTradeMode.FULL
        assert result.tick is not None
        assert result.tick.bid == pytest.approx(4293.2)

    def test_missing_symbol(self, service: MT5Service) -> None:
        service.connect()
        result = service.validate_symbol("NOTAREAL")
        assert result.ok is False
        assert "unavailable" in result.reason.lower() or "not selectable" in result.reason.lower()

    def test_disabled_symbol(self, settings: AppSettings) -> None:
        gw = MockMT5Gateway(
            symbols={"BAD": MockSymbol("BAD", trade_mode=0)}  # DISABLED
        )
        settings.symbol_mappings = {"BAD": "BAD"}
        svc = MT5Service(settings, gateway=gw)
        svc.connect()
        result = svc.validate_symbol("BAD")
        assert result.ok is False
        assert "disabled" in result.reason.lower()

    def test_short_only_rejects_buy(self, settings: AppSettings) -> None:
        gw = MockMT5Gateway(
            symbols={"XAUUSDm": MockSymbol("XAUUSDm", trade_mode=2)}  # SHORTONLY
        )
        settings.symbol_mappings = {"XAUUSD": "XAUUSDm"}
        svc = MT5Service(settings, gateway=gw)
        svc.connect()
        result = svc.validate_symbol("XAUUSD", direction="BUY")
        assert result.ok is False
        assert "short-only" in result.reason.lower()


class TestPricing:
    def test_snapshot_sell_uses_bid(self, service: MT5Service) -> None:
        service.connect()
        snap = service.market_snapshot("XAUUSD", "SELL")
        assert snap.execution_price == pytest.approx(4293.2)  # bid
        assert snap.spread_price == pytest.approx(0.3)
        # point=0.01 → 0.3 / 0.01 = 30 points
        assert snap.spread_points == pytest.approx(30.0)
        assert snap.spec.point == 0.01

    def test_snapshot_buy_uses_ask(self, service: MT5Service) -> None:
        service.connect()
        snap = service.market_snapshot("XAUUSD", "BUY")
        assert snap.execution_price == pytest.approx(4293.5)

    def test_price_to_points_uses_spec(self, service: MT5Service) -> None:
        service.connect()
        pricing = service.pricing
        spec = pricing.get_spec("XAUUSDm")
        diff = pricing.format_price_diff(1.7, spec)
        assert diff["price_difference"] == pytest.approx(1.7)
        assert diff["mt5_points"] == pytest.approx(170.0)  # 1.7 / 0.01

    def test_eurusd_point_size(self, service: MT5Service) -> None:
        service.connect()
        snap = service.market_snapshot("EURUSD", "BUY")
        assert snap.spec.point == pytest.approx(0.00001)
        assert snap.spread_price == pytest.approx(0.00020)
        assert snap.spread_points == pytest.approx(20.0)


class TestNoOrderSendInPhase4Modules:
    def test_pricing_symbols_client_do_not_call_order_send(self, mock_gw: MockMT5Gateway) -> None:
        from pathlib import Path

        from app.mt5 import client, pricing, symbols

        src = (
            Path(client.__file__).read_text(encoding="utf-8")
            + Path(pricing.__file__).read_text(encoding="utf-8")
            + Path(symbols.__file__).read_text(encoding="utf-8")
        )
        assert "order_send" not in src
        # Phase 6 execution module is allowed to wrap order_send
        from app.mt5 import execution

        assert "order_send" in Path(execution.__file__).read_text(encoding="utf-8")
