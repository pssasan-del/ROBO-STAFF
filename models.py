import time
from typing import List, Optional, Literal, Dict, Any, Union
from pydantic import BaseModel, Field

OperatorType = Literal[
    ">", "<", ">=", "<=", "=", "==", "!=",
    "crosses_above", "crosses_below", "between", "near"
]

ConditionType = Literal[
    "ema_compare",
    "sma_compare",
    "rsi",
    "macd",
    "vwap",
    "atr",
    "bollinger",
    "volume_average",
    "open_high",
    "open_low",
    "percentage_change",
    "gap_up",
    "gap_down",
    "crossover",
    "crossunder",
    "breakout",
    "breakdown",
    "candle_bullish",
    "candle_bearish",
    "custom_metric"
]

class StrategyCondition(BaseModel):
    type: ConditionType
    # Indicator parameters
    fast: Optional[int] = None
    slow: Optional[int] = None
    period: Optional[int] = None
    signal: Optional[int] = None
    std_dev: Optional[float] = None
    
    # Comparison & values
    operator: Optional[OperatorType] = ">"
    value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    tolerance_pct: Optional[float] = 0.05  # For open=high, open=low, near checks
    lookback: Optional[int] = 20           # For breakout/breakdown

    # Description for human readability
    description: Optional[str] = None
    
    # Custom field names if comparing metrics (e.g. close, open, vwap, etc.)
    field: Optional[str] = None
    target_field: Optional[str] = None

class StrategyDefinition(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., description="Descriptive name of the strategy")
    timeframe: str = Field(default="5", description="Candle timeframe in minutes or 'D' for Daily")
    universe: str = Field(default="NIFTY50", description="Target stock universe (e.g. NIFTY50, BANKNIFTY, NIFTY100, WATCHLIST)")
    logic: Literal["AND", "OR"] = Field(default="AND", description="Combination logic across conditions")
    conditions: List[StrategyCondition] = Field(default_factory=list, description="Validated list of deterministic conditions")
    created_at: float = Field(default_factory=time.time)
    description: Optional[str] = None

class StockQuote(BaseModel):
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    change: float
    change_pct: float
    timestamp: float = Field(default_factory=time.time)

class ConditionMatchDetail(BaseModel):
    condition_index: int
    condition_desc: str
    actual_value: Optional[str] = None
    passed: bool

class ScanMatch(BaseModel):
    strategy_id: str
    strategy_name: str
    symbol: str
    company_name: Optional[str] = None
    ltp: float
    timeframe: str
    timestamp: float = Field(default_factory=time.time)
    matched_conditions: List[ConditionMatchDetail] = Field(default_factory=list)
    signature: str
    is_mock: bool = False

class ScannerState(BaseModel):
    strategy_id: str
    strategy_name: str
    timeframe: str
    universe: str
    rules: StrategyDefinition
    status: Literal["RUNNING", "PAUSED", "STOPPED"] = "RUNNING"
    created_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    last_scan_at: Optional[float] = None
    last_matches: List[str] = Field(default_factory=list)
    alert_count: int = 0
    total_scans: int = 0
    session_start_time: Optional[float] = None

class MarketStatusOverview(BaseModel):
    market_status: str
    nifty_spot: float
    nifty_change_pct: float
    banknifty_spot: float
    banknifty_change_pct: float
    advances: int
    declines: int
    top_gainers: List[Dict[str, Any]]
    top_losers: List[Dict[str, Any]]
    timestamp: float = Field(default_factory=time.time)
    is_mock: bool = False
