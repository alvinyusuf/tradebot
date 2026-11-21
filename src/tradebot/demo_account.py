"""Read-only startup checks for a BTCUSDT Futures Demo account."""

from dataclasses import dataclass
from decimal import Decimal

from .demo_execution import SYMBOL, DemoExecution, DemoRequestUncertain


@dataclass(frozen=True, slots=True)
class DemoAccountReadiness:
    one_way: bool
    isolated: bool
    auto_add_margin: bool
    leverage: int
    flat: bool
    open_orders: int
    open_algo_orders: int

    @property
    def violations(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, blocked in (
                ("hedge_mode", not self.one_way),
                ("not_isolated", not self.isolated),
                ("auto_add_margin", self.auto_add_margin),
                ("leverage_unconfigured", self.leverage == 0),
                ("leverage_above_limit", self.leverage > 5),
                ("position_present", not self.flat),
                ("open_orders_present", self.open_orders > 0),
                ("open_algo_orders_present", self.open_algo_orders > 0),
            )
            if blocked
        )

    @property
    def ready(self) -> bool:
        return not self.violations


def inspect_demo_account(execution: DemoExecution) -> DemoAccountReadiness:
    """Return BTCUSDT account checks without exposing order IDs or account balances."""
    mode = execution._signed("positionSide/dual", "GET", {}, include_symbol=False)
    settings = execution._signed("symbolConfig", "GET", {}, expect_list=True)
    positions = execution._signed(
        "positionRisk", "GET", {}, expect_list=True, version=3
    )
    orders = execution._signed("openOrders", "GET", {}, expect_list=True)
    algo_orders = execution._signed("openAlgoOrders", "GET", {}, expect_list=True)
    try:
        if any(
            row["symbol"] != SYMBOL
            for entries in (settings, positions, orders, algo_orders)
            for row in entries
        ):
            raise ValueError("Symbol berbeda")
        (symbol,) = settings
        hedge = mode["dualSidePosition"]
        auto_add = symbol["isAutoAddMargin"]
        leverage = symbol["leverage"]
        margin_type = symbol["marginType"]
        if (
            type(hedge) is not bool
            or type(auto_add) is not bool
            or type(leverage) is not int
            or leverage < 0
            or margin_type not in {"CROSSED", "ISOLATED"}
        ):
            raise ValueError("Konfigurasi akun tidak valid")
        sides = [row["positionSide"] for row in positions]
        accepted_sides = {"LONG", "SHORT"} if hedge else {"BOTH"}
        if len(sides) != len(set(sides)) or set(sides) - accepted_sides:
            raise ValueError("Sisi posisi tidak sesuai mode")
        amounts = [Decimal(row["positionAmt"]) for row in positions]
        if not all(amount.is_finite() for amount in amounts):
            raise ValueError("Kuantitas posisi tidak valid")
    except (ArithmeticError, KeyError, TypeError, ValueError):
        raise DemoRequestUncertain(
            "Skema atau keadaan akun Binance Demo tidak konsisten"
        ) from None
    return DemoAccountReadiness(
        one_way=not hedge,
        isolated=margin_type == "ISOLATED",
        auto_add_margin=auto_add,
        leverage=leverage,
        flat=not any(amounts),
        open_orders=len(orders),
        open_algo_orders=len(algo_orders),
    )
