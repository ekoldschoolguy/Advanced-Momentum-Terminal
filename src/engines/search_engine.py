import os
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class SearchEngine:
    """
    In-memory engine for fast searching and filtering of Equity instruments.
    Loads data from the downloaded equities_master.json file.
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.data_file = os.path.join(self.data_dir, "equities_master.json")
        
        self.equities: List[Dict[str, Any]] = []
        
        # Hash maps for O(1) lookups
        self._symbol_map: Dict[str, List[Dict[str, Any]]] = {}
        self._isin_map: Dict[str, List[Dict[str, Any]]] = {}
        
        self.is_loaded = False

    def load_data(self) -> bool:
        """Loads and indexes the equity instruments from the local JSON file."""
        if not os.path.exists(self.data_file):
            logger.error(f"Data file {self.data_file} not found. Download the master file first.")
            return False
            
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                all_instruments = json.load(f)
                
            # Filter Equity instruments and NSE Indices
            self.equities = [
                inst for inst in all_instruments
                if (inst.get('segment') in ['NSE_EQ', 'BSE_EQ'] and inst.get('instrument_type') == 'EQ') or
                   (inst.get('segment') == 'NSE_INDEX' and inst.get('instrument_type') == 'INDEX')
            ]
            
            # Rebuild indexes
            self._symbol_map.clear()
            self._isin_map.clear()
            
            for eq in self.equities:
                symbol = eq.get('trading_symbol', '').upper()
                isin = eq.get('isin', '').upper()
                
                if symbol:
                    if symbol not in self._symbol_map:
                        self._symbol_map[symbol] = []
                    self._symbol_map[symbol].append(eq)
                    
                if isin:
                    if isin not in self._isin_map:
                        self._isin_map[isin] = []
                    self._isin_map[isin].append(eq)
                    
            self.is_loaded = True
            logger.info(f"SearchEngine loaded successfully with {len(self.equities)} equities.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load equity data: {e}")
            return False

    def search_by_symbol(self, symbol: str, exact_match: bool = False) -> List[Dict[str, Any]]:
        """Search equities by trading symbol (e.g., RELIANCE)"""
        if not self.is_loaded:
            return []
            
        symbol = symbol.upper()
        if exact_match:
            return self._symbol_map.get(symbol, [])
            
        # Partial match
        return [eq for eq in self.equities if symbol in eq.get('trading_symbol', '').upper()]

    def search_by_name(self, name_query: str) -> List[Dict[str, Any]]:
        """Search equities by company name (e.g., JOCIL LIMITED)"""
        if not self.is_loaded:
            return []
            
        name_query = name_query.upper()
        return [
            eq for eq in self.equities 
            if name_query in eq.get('name', '').upper() or name_query in eq.get('short_name', '').upper()
        ]

    def get_by_isin(self, isin: str) -> List[Dict[str, Any]]:
        """Get an equity directly by its ISIN for exact cross-exchange matches"""
        if not self.is_loaded:
            return []
            
        return self._isin_map.get(isin.upper(), [])
        
    def get_stats(self) -> Dict[str, Any]:
        """Returns basic statistics about the loaded equity data"""
        nse_count = sum(1 for eq in self.equities if eq.get('exchange') == 'NSE')
        bse_count = sum(1 for eq in self.equities if eq.get('exchange') == 'BSE')
        
        return {
            "total_equities": len(self.equities),
            "nse_equities": nse_count,
            "bse_equities": bse_count,
            "is_loaded": self.is_loaded
        }
