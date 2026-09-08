"""Gambling Financial Ledger, Winrate State Machine, and Tilt-Chasing Engine.

Tracks cumulative Net PnL ($), session winrate %, streaks, experienced RTP %,
multiplier distributions, and alerts on loss-chasing bet escalation (Martingale tilt).
"""

from collections import deque
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GamblingLedger:
    """Manages session accounting, spin analytics, and behavioral gambling risk indicators."""

    def __init__(
        self,
        initial_balance: Optional[float] = None,
        baseline_bet: Optional[float] = None,
        big_win_multiplier: float = 50.0,
        big_win_dollars: float = 2500.0,
        on_big_win: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_tilt_bet: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.starting_balance: Optional[float] = initial_balance
        self.current_balance: float = initial_balance or 0.0
        self.peak_balance: float = initial_balance or 0.0
        self.baseline_bet: float = baseline_bet or 0.0
        self.current_bet: float = baseline_bet or 0.0

        # Thresholds & Callbacks
        self.big_win_multiplier = big_win_multiplier
        self.big_win_dollars = big_win_dollars
        self.on_big_win = on_big_win
        self.on_tilt_bet = on_tilt_bet

        # Cumulative Financials
        self.total_wagered: float = 0.0
        self.total_payout: float = 0.0

        # Spin Analytics
        self.total_spins: int = 0
        self.winning_spins: int = 0
        self.losing_spins: int = 0
        self.current_streak: int = 0  # +N for wins, -N for losses
        self.max_win_streak: int = 0
        self.max_loss_streak: int = 0

        # Multiplier Buckets
        self.multiplier_distribution = {
            "<2x": 0,
            "2x-10x": 0,
            "10x-50x": 0,
            "50x-100x": 0,
            "100x+": 0,
        }

        # Loss Chasing / Tilt State
        self.is_chasing_losses: bool = False
        self.last_spin_state: str = "IDLE"
        self.last_recorded_win: float = 0.0

        # Rolling PnL history for sparkline UI (last 100 data points)
        self.pnl_history: deque = deque(maxlen=100)

    def set_starting_balance(self, amount: float):
        """Sets or resets the starting balance anchor."""
        self.starting_balance = float(amount)
        self.current_balance = float(amount)
        self.peak_balance = float(amount)
        logger.info("[GamblingLedger] Set starting balance to $%.2f", self.starting_balance)

    def record_spin_outcome(self, bet_amount: float, win_amount: float, multiplier: Optional[float] = None):
        """Records a resolved spin/bet outcome and updates ledger metrics."""
        bet = max(0.0, float(bet_amount))
        win = max(0.0, float(win_amount))

        if self.baseline_bet == 0.0 and bet > 0.0:
            self.baseline_bet = bet

        self.current_bet = bet
        self.total_wagered += bet
        self.total_payout += win
        self.total_spins += 1

        # Calculate implied multiplier if not explicitly parsed
        mult = multiplier if multiplier and multiplier > 0.0 else (win / bet if bet > 0 else 0.0)

        # Streak & Win/Loss classification
        if win > 0.0:
            self.winning_spins += 1
            self.current_streak = self.current_streak + 1 if self.current_streak > 0 else 1
            self.max_win_streak = max(self.max_win_streak, self.current_streak)
        else:
            self.losing_spins += 1
            self.current_streak = self.current_streak - 1 if self.current_streak < 0 else -1
            self.max_loss_streak = min(self.max_loss_streak, self.current_streak)

        # Multiplier distribution
        if mult >= 100.0:
            self.multiplier_distribution["100x+"] += 1
        elif mult >= 50.0:
            self.multiplier_distribution["50x-100x"] += 1
        elif mult >= 10.0:
            self.multiplier_distribution["10x-50x"] += 1
        elif mult >= 2.0:
            self.multiplier_distribution["2x-10x"] += 1
        else:
            self.multiplier_distribution["<2x"] += 1

        # Check Loss Chasing (Martingale Tilt Alert)
        # Condition: 3+ consecutive losses and bet size doubled from baseline
        if self.current_streak <= -3 and self.baseline_bet > 0:
            escalation_ratio = bet / self.baseline_bet
            if escalation_ratio >= 1.95:
                self.is_chasing_losses = True
                logger.warning(
                    "[GamblingLedger] TILT BET ALERT: Streamer escalated bet %.1fx ($%.2f vs baseline $%.2f) on streak %d",
                    escalation_ratio,
                    bet,
                    self.baseline_bet,
                    self.current_streak,
                )
                if self.on_tilt_bet:
                    try:
                        self.on_tilt_bet({
                            "escalation_ratio": escalation_ratio,
                            "current_bet": bet,
                            "baseline_bet": self.baseline_bet,
                            "loss_streak": abs(self.current_streak),
                        })
                    except Exception as e:
                        logger.error("[GamblingLedger] Error in tilt bet callback: %s", e)
            else:
                self.is_chasing_losses = False
        else:
            self.is_chasing_losses = False

        # Check Big Win Trigger
        is_big_win = (win >= self.big_win_dollars) or (mult >= self.big_win_multiplier)
        if is_big_win and self.on_big_win:
            try:
                self.on_big_win({
                    "win_amount": win,
                    "multiplier": mult,
                    "bet": bet,
                })
            except Exception as e:
                logger.error("[GamblingLedger] Error in big win callback: %s", e)

    def update_from_ocr(self, ocr_data: Dict[str, Any]):
        """Consumes real-time OCR telemetry and updates ledger state."""
        bal = ocr_data.get("balance")
        bet = ocr_data.get("bet")
        win = ocr_data.get("win")
        mult = ocr_data.get("multiplier")
        spin_state = ocr_data.get("spin_state", "IDLE")

        # Auto-initialize starting balance on first valid reading
        if bal is not None and bal > 0:
            if self.starting_balance is None:
                self.set_starting_balance(bal)
            self.current_balance = bal
            self.peak_balance = max(self.peak_balance, bal)

        # Baseline bet adaptation
        if bet is not None and bet > 0:
            self.current_bet = bet
            if self.baseline_bet == 0.0:
                self.baseline_bet = bet

        # Detect spin completion transition: SPINNING -> IDLE or WIN_CELEBRATION
        if self.last_spin_state == "SPINNING" and spin_state in ("IDLE", "WIN_CELEBRATION"):
            actual_win = win if (win is not None and win > 0) else 0.0
            actual_bet = self.current_bet if self.current_bet > 0 else 10.0
            self.record_spin_outcome(actual_bet, actual_win, multiplier=mult)

        self.last_spin_state = spin_state
        if win is not None:
            self.last_recorded_win = win

        # Record rolling Net PnL
        net_pnl = self.get_net_pnl()
        self.pnl_history.append({
            "t": time.time(),
            "pnl": net_pnl,
            "bal": self.current_balance,
        })

    def get_net_pnl(self) -> float:
        """Calculates current net profit or loss."""
        if self.starting_balance is not None:
            return round(self.current_balance - self.starting_balance, 2)
        # Fallback to cumulative payouts minus wagers
        return round(self.total_payout - self.total_wagered, 2)

    def get_drawdown(self) -> Tuple[float, float]:
        """Calculates drawdown from peak balance (in $ and %)."""
        if self.peak_balance <= 0:
            return 0.0, 0.0
        dd_dollars = max(0.0, self.peak_balance - self.current_balance)
        dd_pct = round((dd_dollars / self.peak_balance) * 100.0, 1)
        return round(dd_dollars, 2), dd_pct

    def get_winrate_pct(self) -> float:
        """Calculates Hit Frequency (% of spins that produced a win)."""
        if self.total_spins == 0:
            return 0.0
        return round((self.winning_spins / self.total_spins) * 100.0, 1)

    def get_experienced_rtp(self) -> float:
        """Calculates experienced Return to Player (% of wagers returned as payouts)."""
        if self.total_wagered <= 0:
            return 100.0
        return round((self.total_payout / self.total_wagered) * 100.0, 1)

    def get_summary(self) -> Dict[str, Any]:
        """Returns comprehensive gambling session metrics."""
        dd_dollars, dd_pct = self.get_drawdown()
        return {
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "net_pnl": self.get_net_pnl(),
            "peak_balance": self.peak_balance,
            "drawdown_dollars": dd_dollars,
            "drawdown_pct": dd_pct,
            "current_bet": self.current_bet,
            "baseline_bet": self.baseline_bet,
            "total_wagered": round(self.total_wagered, 2),
            "total_payout": round(self.total_payout, 2),
            "experienced_rtp": self.get_experienced_rtp(),
            "total_spins": self.total_spins,
            "winning_spins": self.winning_spins,
            "losing_spins": self.losing_spins,
            "winrate_pct": self.get_winrate_pct(),
            "current_streak": self.current_streak,
            "max_win_streak": self.max_win_streak,
            "max_loss_streak": self.max_loss_streak,
            "multiplier_distribution": self.multiplier_distribution,
            "is_chasing_losses": self.is_chasing_losses,
            "pnl_history": list(self.pnl_history),
        }
