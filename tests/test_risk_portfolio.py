from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from unittest import TestCase

from tradebot.portfolio import Portfolio
from tradebot.risk import DailyRisk, MaintenanceBracket, OrderFilters, Side, size_entry

BASE_FILTERS = OrderFilters(D(".1"), D(".001"), D(".001"), D(100), D(1))
BRACKETS = (MaintenanceBracket(D(0), D(100000), D(".004"), D(0), 125),)
NOW = datetime(2024, 1, 1, tzinfo=UTC)


def sized(side=Side.LONG, **overrides):
    inputs = {
        "side": side,
        "entry_price": D(100),
        "atr": D("2.03"),
        "day_start_equity": D(100),
        "equity": D(100),
        "available_balance": D(100),
        "filters": BASE_FILTERS,
        "brackets": BRACKETS,
    }
    inputs.update(overrides)
    return size_entry(**inputs)


class RiskTests(TestCase):
    def test_rounds_protection_outward_and_keeps_risk_within_budget(self):
        long = sized().plan
        short = sized(Side.SHORT).plan
        self.assertEqual(
            (long.stop_price, long.take_profit_price), (D("96.9"), D("106.1"))
        )
        self.assertEqual(
            (short.stop_price, short.take_profit_price), (D("103.1"), D("93.9"))
        )
        for plan in (long, short):
            self.assertLessEqual(plan.loss_at_stop, D(".5"))
            self.assertGreater(
                plan.loss_at_stop / plan.quantity * (plan.quantity + D(".001")), D(".5")
            )
            self.assertEqual(plan.leverage, 1)

    def test_minimum_filter_cannot_increase_risk(self):
        strict = OrderFilters(D(".1"), D(".001"), D(".001"), D(100), D(50))
        self.assertEqual(sized(filters=strict).reason, "minimum_order")

    def test_smallest_leverage_for_largest_compliant_quantity(self):
        result = sized(atr=D(".01"), fee_rate=D(0), exit_slippage=D(0))
        self.assertEqual(result.plan.leverage, 5)
        self.assertEqual(result.plan.quantity, D("1.25"))
        self.assertEqual(result.plan.initial_margin, D(25))

    def test_funding_and_allocated_risk_can_reduce_size(self):
        base = sized(equity=D("95.4")).plan
        allocated = sized(equity=D("95.4"), allocated_risk=D(".1")).plan
        reserved = sized(equity=D("95.4"), funding_reserve=D(".001")).plan
        self.assertLess(allocated.quantity, base.quantity)
        self.assertLess(reserved.quantity, base.quantity)

    def test_daily_halt_survives_restart_and_incomplete_reconciliation(self):
        risk = DailyRisk(date(2024, 1, 1), D(100))
        self.assertEqual(risk.remaining_budget(D(200)), D(5))
        self.assertTrue(risk.observe(NOW, D(95), flat=False))
        resumed = DailyRisk(**asdict(risk))
        self.assertTrue(resumed.observe(NOW, D(100), flat=True))
        tomorrow = NOW + timedelta(days=1)
        self.assertTrue(resumed.observe(tomorrow, D(96), flat=True, reconciled=False))
        self.assertFalse(resumed.observe(tomorrow, D(96), flat=True))
        self.assertEqual(resumed.day_start_equity, D(96))
        resumed.halt_system()
        self.assertTrue(resumed.observe(tomorrow + timedelta(days=1), D(96), flat=True))
        resumed.recover_system(flat=True, reconciled=True)
        self.assertFalse(resumed.entry_halted)


class PortfolioTests(TestCase):
    def test_fee_funding_and_realized_ledger_are_consistent_for_both_sides(self):
        for side in Side:
            with self.subTest(side=side):
                plan = sized(side).plan
                wallet = Portfolio(D(100))
                position = wallet.open(plan, NOW, D(".0005"))
                self.assertEqual(
                    wallet.available_balance,
                    D(100) - position.entry_fee - plan.initial_margin,
                )
                funding = wallet.settle_funding(D(101), D(".001"))
                self.assertEqual(funding, -side * plan.quantity * D(".101"))
                self.assertEqual(
                    wallet.equity(D(102)), wallet.balance + 2 * side * plan.quantity
                )
                trade = wallet.close(
                    D(102), NOW + timedelta(minutes=2), D(".0005"), "stop"
                )
                self.assertEqual(wallet.balance - D(100), trade.net_pnl)
                self.assertEqual(wallet.total_fees, trade.entry_fee + trade.exit_fee)
                self.assertEqual(wallet.total_funding, funding)
                self.assertEqual(wallet.realized_pnl, trade.gross_pnl)
                self.assertIsNone(wallet.position)
