from strategy.models.ou_reversion import OUReversionModel
from strategy.models.vwap_reversion import VWAPReversionModel
from strategy.models.trend_cont import TrendContinuationModel
from strategy.models.sweep_reversal import SweepReversalModel

ALL_MODELS = [SweepReversalModel, OUReversionModel, VWAPReversionModel, TrendContinuationModel]
