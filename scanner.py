import asyncio
import time
from typing import Dict, List, Optional, Callable, Any
from config import settings, logger
from models import StrategyDefinition, ScannerState, ScanMatch
from symbol_universe import SymbolUniverse
from fyers_service import fyers_service
from strategy_engine import StrategyEngine
from alerts import AlertManager
from storage import storage
from errors import MarketDataUnavailable

class ContinuousScanner:
    """
    Continuous Background Strategy Scanner.
    Features:
    - Multi-strategy independent scanning
    - Non-blocking execution
    - Configurable automatic safety shutoff session timer
    - Deduplicated Telegram alert dispatch
    - START, PAUSE, RESUME, STOP controls
    """

    def __init__(self, alert_callback: Optional[Callable[[str], Any]] = None):
        self._scanners: Dict[str, ScannerState] = {}
        self._is_running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._alert_callback = alert_callback
        self._session_start_time: Optional[float] = None
        self._max_session_seconds = settings.MAX_SCANNER_SESSION_HOURS * 3600
        self._last_scan_bucket: Dict[str, int] = {}

    def set_alert_callback(self, callback: Callable[[str], Any]):
        self._alert_callback = callback

    def add_scanner(self, strategy: StrategyDefinition) -> ScannerState:
        strat_id = strategy.id or f"scan_{int(time.time()*1000)}"
        strategy.id = strat_id
        
        # Save to SQLite
        storage.save_strategy(strategy)

        state = ScannerState(
            strategy_id=strat_id,
            strategy_name=strategy.name,
            timeframe=strategy.timeframe,
            universe=strategy.universe,
            rules=strategy,
            status="RUNNING",
            created_at=time.time(),
            started_at=time.time(),
            session_start_time=time.time()
        )
        self._scanners[strat_id] = state
        storage.update_scanner_state(state)
        
        if self._session_start_time is None:
            self._session_start_time = time.time()

        logger.info(f"[SCANNER] Added & Started scanner: {strategy.name} (ID: {strat_id})")
        return state

    def pause_scanner(self, strategy_id_or_name: str) -> bool:
        scanner = self._find_scanner(strategy_id_or_name)
        if scanner:
            scanner.status = "PAUSED"
            storage.update_scanner_state(scanner)
            logger.info(f"[SCANNER] Paused scanner: {scanner.strategy_name}")
            return True
        return False

    def resume_scanner(self, strategy_id_or_name: str) -> bool:
        scanner = self._find_scanner(strategy_id_or_name)
        if scanner:
            scanner.status = "RUNNING"
            storage.update_scanner_state(scanner)
            logger.info(f"[SCANNER] Resumed scanner: {scanner.strategy_name}")
            return True
        return False

    def stop_scanner(self, strategy_id_or_name: str) -> bool:
        scanner = self._find_scanner(strategy_id_or_name)
        if scanner:
            scanner.status = "STOPPED"
            storage.update_scanner_state(scanner)
            del self._scanners[scanner.strategy_id]
            logger.info(f"[SCANNER] Stopped scanner: {scanner.strategy_name}")
            return True
        return False

    def stop_all(self) -> int:
        count = len(self._scanners)
        for s in list(self._scanners.values()):
            s.status = "STOPPED"
            storage.update_scanner_state(s)
        self._scanners.clear()
        self._session_start_time = None
        logger.info(f"[SCANNER] Stopped all active scanners ({count} total)")
        return count

    def get_active_scanners(self) -> List[ScannerState]:
        return list(self._scanners.values())

    def _find_scanner(self, identifier: str) -> Optional[ScannerState]:
        ident = identifier.strip().lower()
        if ident in self._scanners:
            return self._scanners[ident]
        for s in self._scanners.values():
            if s.strategy_id.lower() == ident or s.strategy_name.lower() == ident:
                return s
            if ident in s.strategy_name.lower():
                return s
        return None

    def scan_single_strategy(self, strategy: StrategyDefinition) -> List[ScanMatch]:
        """
        Executes a deterministic one-time scan across the strategy's universe.
        """
        symbols = SymbolUniverse.get_universe(strategy.universe)
        matches: List[ScanMatch] = []
        if not settings.MOCK_MARKET_DATA and not fyers_service.is_healthy():
            raise MarketDataUnavailable(
                "FYERS live data is offline or the token has expired. Scanner was not run; mock data was NOT substituted."
            )
        is_mock = settings.MOCK_MARKET_DATA

        for sym in symbols:
            try:
                candles = fyers_service.get_history(sym, timeframe=strategy.timeframe)
                match = StrategyEngine.evaluate_strategy(strategy, sym, candles, is_mock=is_mock)
                if match:
                    matches.append(match)
            except Exception as e:
                logger.error(f"[SCANNER] Error evaluating {sym} on {strategy.name}: {e}")

        return matches

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
        tf = str(timeframe).upper().strip()
        if tf in ("D", "1D"):
            return 86400
        try:
            return max(60, int(tf) * 60)
        except ValueError:
            return 300

    def _scan_due(self, state: ScannerState) -> bool:
        """Run at most once per candle bucket for candle-based strategies."""
        seconds = self._timeframe_seconds(state.timeframe)
        bucket = int(time.time() // seconds)
        last = self._last_scan_bucket.get(state.strategy_id)
        if last == bucket:
            return False
        self._last_scan_bucket[state.strategy_id] = bucket
        return True

    async def run_loop(self):
        """
        Continuous background loop evaluating active strategies.
        Checks for configured maximum session limit.
        """
        self._is_running = True
        logger.info("[SCANNER] Background scanner loop initialized")

        while self._is_running:
            try:
                # 1. Check configured Session Limit
                if self._session_start_time and (time.time() - self._session_start_time >= self._max_session_seconds):
                    logger.warning(f"[SCANNER] {settings.MAX_SCANNER_SESSION_HOURS}-hour continuous session limit reached. Stopping scanners.")
                    active_count = len(self._scanners)
                    self.stop_all()
                    
                    if self._alert_callback and active_count > 0:
                        msg = f"⏱ *Scanner session automatically stopped after {settings.MAX_SCANNER_SESSION_HOURS} hours of continuous operation.*"
                        if asyncio.iscoroutinefunction(self._alert_callback):
                            await self._alert_callback(msg)
                        else:
                            self._alert_callback(msg)
                    # Keep the background loop alive so a later START can begin a new session.
                    await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)
                    continue

                # 2. Iterate through all active running scanners
                active_scanners = [s for s in self._scanners.values() if s.status == "RUNNING"]
                
                for state in active_scanners:
                    if not self._scan_due(state):
                        continue
                    logger.info(f"[SCAN] Running candle-close scan for {state.strategy_name} ({state.universe} / {state.timeframe})")
                    try:
                        matches = self.scan_single_strategy(state.rules)
                    except MarketDataUnavailable as e:
                        state.status = "PAUSED"
                        storage.update_scanner_state(state)
                        logger.error(f"[SCANNER] Paused '{state.strategy_name}' because live FYERS data is unavailable: {e}")
                        if self._alert_callback:
                            msg = f"⚠️ *Scanner Paused*\n{state.strategy_name}\n\nFYERS live market data is unavailable. No mock data was used. Refresh the FYERS token and resume the scanner."
                            if asyncio.iscoroutinefunction(self._alert_callback):
                                await self._alert_callback(msg)
                            else:
                                self._alert_callback(msg)
                        continue
                    
                    state.last_scan_at = time.time()
                    state.total_scans += 1
                    state.last_matches = [m.symbol for m in matches]
                    
                    # Dispatch alerts
                    for match in matches:
                        if AlertManager.should_send_alert(match):
                            state.alert_count += 1
                            logger.info(f"[MATCH] {match.symbol} matched strategy '{state.strategy_name}'")
                            if self._alert_callback:
                                alert_msg = AlertManager.format_telegram_alert(match)
                                try:
                                    if asyncio.iscoroutinefunction(self._alert_callback):
                                        await self._alert_callback(alert_msg)
                                    else:
                                        self._alert_callback(alert_msg)
                                except Exception as e:
                                    logger.error(f"[SCANNER] Alert callback error: {e}")

                    storage.update_scanner_state(state)

            except Exception as e:
                logger.error(f"[SCANNER] Exception in scanner loop: {e}")

            # Sleep for interval
            await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

scanner = ContinuousScanner()
