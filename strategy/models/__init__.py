from strategy.models.ou_reversion import OUReversionModel
from strategy.models.vwap_reversion import VWAPReversionModel
from strategy.models.trend_cont import TrendContinuationModel
from strategy.models.sweep_reversal import SweepReversalModel
from strategy.models.ema_reversion import EMAReversionModel
from strategy.models.kalman_momentum import KalmanMomentumModel
from strategy.models.afternoon_momentum import AfternoonMomentumModel
from strategy.models.or_reversion import ORReversionModel
from strategy.models.pd_level_reversion import PDLevelReversionModel

ALL_MODELS = [
    OUReversionModel,
    PDLevelReversionModel,
    VWAPReversionModel,
    ORReversionModel,
    EMAReversionModel,
    SweepReversalModel,
    KalmanMomentumModel,
    TrendContinuationModel,
    AfternoonMomentumModel,
]
