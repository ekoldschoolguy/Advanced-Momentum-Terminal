from src.managers.auth_manager import AuthManager
from src.managers.instrument_manager import InstrumentManager
from src.managers.universe_manager import UniverseManager
from src.engines.search_engine import SearchEngine
from src.engines.historical_engine import HistoricalEngine
from src.engines.performance_engine import PerformanceEngine
from src.engines.trend_engine import TrendEngine
from src.engines.indices_etf_engine import IndicesEtfEngine

from src.engines.mtf_engine import MTFEngine

# Services
auth_manager = AuthManager(env_file=".env", token_file="token.json")
instrument_manager = InstrumentManager(auth_manager=auth_manager)
universe_manager = UniverseManager(data_dir="data/universes")
search_engine = SearchEngine(data_dir="data")
historical_engine = HistoricalEngine(auth_manager=auth_manager)
performance_engine = PerformanceEngine(historical_engine=historical_engine)
trend_engine = TrendEngine(historical_engine=historical_engine)
indices_etf_engine = IndicesEtfEngine(historical_engine=historical_engine, search_engine=search_engine)
mtf_engine = MTFEngine()

