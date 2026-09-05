from typing import Literal
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    totp: str = Field(min_length=6, max_length=8)

class Subscription(BaseModel):
    exchange_segment: str
    instrument_token: str
    mode: Literal["scrip", "lite", "depth", "full_depth", "index"] = "scrip"


class ScannerStartRequest(BaseModel):
    group: Literal["A", "B"]

class InstrumentSearchRequest(BaseModel):
    exchange_segment: str
    symbol: str
    expiry: str | None = None
    option_type: str | None = None
    strike_price: str | None = None
    ignore_50multiple: bool = False

class OptionResolveRequest(BaseModel):
    underlying: str
    expiry: str
    option_type: Literal["CE", "PE"]
    strike_price: float
    exchange_segment: str = "NSEFO"

class SignalEvalRequest(BaseModel):
    symbol_key: str
    timeframe_sec: int = 300
    closed_only: bool = True

class RiskCheckRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    reference_price: float
    live_price: float | None = None
    open_positions: int = 0
    day_pnl: float = 0.0

class TradingToggle(BaseModel):
    enabled: bool

class OrderRequest(BaseModel):
    exchange_segment: str
    product: str
    price: str = "0"
    order_type: str
    quantity: str
    validity: str = "DAY"
    trading_symbol: str
    transaction_type: Literal["B", "S", "BUY", "SELL"]
    trigger_price: str = "0"
    amo: str = "NO"
    tag: str | None = None

class OptionScanRequest(BaseModel):
    underlying: str
    expiry: str
    option_type: Literal["CE", "PE"]
    underlying_ltp: float = Field(gt=0)
    strike_step: float = Field(gt=0)
    strikes_each_side: int = Field(default=2, ge=0, le=10)
    exchange_segment: str = "NSEFO"

class OptionRankRequest(BaseModel):
    underlying_ltp: float = Field(gt=0)
    option_type: Literal["CE", "PE"]
    exchange_segment: str = "NSEFO"
    records: list[dict]

class LifecycleCreateRequest(BaseModel):
    symbol_key: str
    side: Literal["BUY", "SELL"]
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target1: float = Field(gt=0)
    target2: float = Field(gt=0)
    ttl_sec: int = Field(default=1800, ge=30, le=86400)

class LifecyclePriceRequest(BaseModel):
    price: float = Field(gt=0)

class ExecutionArmRequest(BaseModel):
    enabled: bool

class ExecutionIntentRequest(BaseModel):
    exchange_segment: str
    product: str
    price: str = "0"
    order_type: str
    quantity: int = Field(gt=0)
    validity: str = "DAY"
    trading_symbol: str
    transaction_type: Literal["B", "S", "BUY", "SELL"]
    trigger_price: str = "0"
    amo: str = "NO"
    disclosed_quantity: str = "0"
    reference_price: float = Field(gt=0)
    live_price: float | None = Field(default=None, gt=0)
    open_positions: int = Field(default=0, ge=0)
    day_pnl: float = 0.0
    signal_id: str | None = None

class ExecutionConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=10)
    live_price: float | None = Field(default=None, gt=0)
    open_positions: int = Field(default=0, ge=0)
    day_pnl: float = 0.0

class OrderCancelRequest(BaseModel):
    order_id: str = Field(min_length=1)
    amo: str = "NO"

class OrderModifyRequest(BaseModel):
    order_id: str = Field(min_length=1)
    price: str
    order_type: str
    quantity: str
    validity: str = "DAY"
    trigger_price: str = "0"
    disclosed_quantity: str = "0"
    amo: str = "NO"

class PositionExitRequest(BaseModel):
    position_key: str = Field(min_length=3)
    quantity: int | None = Field(default=None, gt=0)

class ExitPlanRequest(BaseModel):
    position_key: str = Field(min_length=3)
    stop_loss: float | None = Field(default=None, gt=0)
    target1: float | None = Field(default=None, gt=0)
    target2: float | None = Field(default=None, gt=0)
    target1_fraction: float = Field(default=0.5, gt=0, le=1)
    auto_exit: bool = False

class ExitAllConfirmRequest(BaseModel):
    confirmation_text: str
