import os
import csv
import logging
import httpx
from typing import List, Dict

logger = logging.getLogger(__name__)

class UniverseManager:
    """
    Downloads and manages predefined stock universes (Nifty 500, Midcap Select, etc.)
    """
    
    UNIVERSES = {
        "Nifty 50": "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
        "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "Nifty 200": "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
        "Nifty Midcap Select": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcapselect_list.csv",
        "Nifty Microcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv",
        "Nifty Auto": "https://www.niftyindices.com/IndexConstituent/ind_niftyautolist.csv",
        "Nifty Bank": "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv",
        "Nifty Cement": "https://niftyindices.com/IndexConstituent/ind_NiftyCement_list.csv",
        "Nifty Chemicals": "https://niftyindices.com/IndexConstituent/ind_niftyChemicals_list.csv",
        "Nifty Fin Service": "https://www.niftyindices.com/IndexConstituent/ind_niftyfinancelist.csv",
        "Nifty FMCG": "https://www.niftyindices.com/IndexConstituent/ind_niftyfmcglist.csv",
        "NIFTY HEALTHCARE": "https://www.niftyindices.com/IndexConstituent/ind_niftyhealthcarelist.csv",
        "Nifty IT": "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv",
        "Nifty Media": "https://www.niftyindices.com/IndexConstituent/ind_niftymedialist.csv",
        "Nifty Pharma": "https://www.niftyindices.com/IndexConstituent/ind_niftypharmalist.csv",
        "Nifty Pvt Bank": "https://www.niftyindices.com/IndexConstituent/ind_nifty_privatebanklist.csv",
        "Nifty PSU Bank": "https://www.niftyindices.com/IndexConstituent/ind_niftypsubanklist.csv",
        "Nifty Realty": "https://www.niftyindices.com/IndexConstituent/ind_niftyrealtylist.csv",
        "NIFTY CONSR DURBL": "https://www.niftyindices.com/IndexConstituent/ind_niftyconsumerdurableslist.csv",
        "NIFTY OIL AND GAS": "https://www.niftyindices.com/IndexConstituent/ind_niftyoilgaslist.csv",
        "Nifty500 Health": "https://niftyindices.com/IndexConstituent/ind_nifty500Healthcare_list.csv",
        "Nifty Metal": "https://www.niftyindices.com/IndexConstituent/ind_niftymetallist.csv",
        "Nifty PSE": "https://www.niftyindices.com/IndexConstituent/ind_niftypselist.csv",
        "Nifty Energy": "https://www.niftyindices.com/IndexConstituent/ind_niftyenergylist.csv",
        "Nifty MS Fin Serv": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallfinancailservice_list.csv",
        "Nifty MidSml Hlth": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallhealthcare_list.csv",
        "Nifty MS IT Telcm": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallitAndtelecom_list.csv",
        "Nifty Next 50": "https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv",
        "Nifty 100": "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
        "Nifty Total Market": "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
        "Nifty500 Multicap 50:25:25": "https://www.niftyindices.com/IndexConstituent/ind_nifty500Multicap502525_list.csv",
        "Nifty500 LargeMidSmall Equal-Cap Weighted": "https://www.niftyindices.com/IndexConstituent/ind_Nifty500_LMS_Equal-Cap_Weighted_list.csv",
        "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
        "Nifty Midcap 50": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap50list.csv",
        "Nifty Midcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap100list.csv",
        "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
        "Nifty Smallcap 50": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap50list.csv",
        "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
        "Nifty LargeMidcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv",
        "Nifty MidSmallcap 400": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallcap400list.csv",
        "Nifty MidSmallcap400 50:50": "https://www.niftyindices.com/IndexConstituent/ind_niftymidsmallcap4005050list.csv",
        "Nifty India FPI 150": "https://www.niftyindices.com/IndexConstituent/ind_niftyindiafpi150list.csv"
    }

    def __init__(self, data_dir: str = "data/universes"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.universe_symbols: Dict[str, List[str]] = {}

    async def download_all(self):
        """Downloads all universe CSVs and loads them."""
        import shutil
        from datetime import datetime
        import io
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
        }
        
        archive_dir = os.path.join(self.data_dir, "archive")
        
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            for name, url in self.UNIVERSES.items():
                file_path = os.path.join(self.data_dir, f"{name.replace(' ', '_')}.csv")
                try:
                    logger.info(f"Downloading {name} universe...")
                    response = await client.get(url)
                    if response.status_code == 200:
                        new_content = response.content
                        
                        # Parse symbols from the downloaded content
                        new_symbols = []
                        try:
                            text_stream = io.StringIO(new_content.decode('utf-8-sig'))
                            reader = csv.DictReader(text_stream)
                            if reader.fieldnames:
                                symbol_col = next((col for col in reader.fieldnames if col and 'symbol' in col.lower()), None)
                                if symbol_col:
                                    for row in reader:
                                        sym = row.get(symbol_col, "").strip()
                                        if sym:
                                            new_symbols.append(sym)
                        except Exception as parse_err:
                            logger.error(f"Error parsing downloaded CSV for {name}: {parse_err}")
                        
                        # Parse symbols from the existing file if it exists
                        old_symbols = []
                        if os.path.exists(file_path):
                            try:
                                with open(file_path, "r", encoding="utf-8-sig") as f:
                                    reader = csv.DictReader(f)
                                    if reader.fieldnames:
                                        symbol_col = next((col for col in reader.fieldnames if col and 'symbol' in col.lower()), None)
                                        if symbol_col:
                                            for row in reader:
                                                sym = row.get(symbol_col, "").strip()
                                                if sym:
                                                    old_symbols.append(sym)
                            except Exception as read_err:
                                logger.error(f"Error reading existing CSV for {name}: {read_err}")
                        
                        # Compare symbol lists
                        if os.path.exists(file_path) and set(old_symbols) != set(new_symbols) and len(new_symbols) > 0:
                            os.makedirs(archive_dir, exist_ok=True)
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            archive_path = os.path.join(archive_dir, f"{name.replace(' ', '_')}_{timestamp}.csv")
                            logger.info(f"Symbols changed for {name}. Archiving old file to {archive_path}")
                            shutil.move(file_path, archive_path)
                        
                        # Save the new file
                        with open(file_path, "wb") as f:
                            f.write(new_content)
                    else:
                        logger.error(f"Failed to download {name}: Status {response.status_code}")
                except Exception as e:
                    logger.error(f"Error downloading {name}: {e}")
                    
        self.load_all()
        
    def load_all(self):
        """Loads symbols from local CSV files into memory."""
        for name in self.UNIVERSES.keys():
            file_path = os.path.join(self.data_dir, f"{name.replace(' ', '_')}.csv")
            symbols = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8-sig") as f:
                        reader = csv.DictReader(f)
                        # Find the symbol column (could be 'Symbol', 'Symbol ', etc.)
                        if not reader.fieldnames:
                            continue
                        symbol_col = next((col for col in reader.fieldnames if col and 'symbol' in col.lower()), None)
                        
                        if symbol_col:
                            for row in reader:
                                sym = row.get(symbol_col, "").strip()
                                if sym:
                                    symbols.append(sym)
                except Exception as e:
                    logger.error(f"Error reading {name} CSV: {e}")
                    
            self.universe_symbols[name] = symbols
            logger.info(f"Loaded {len(symbols)} symbols for {name}")

    def get_symbols(self, universe_name: str) -> List[str]:
        return self.universe_symbols.get(universe_name, [])

    def get_symbol_industries(self) -> Dict[str, str]:
        mapping = {}
        file_path = os.path.join(self.data_dir, "Nifty_500.csv")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames:
                        symbol_col = next((col for col in reader.fieldnames if col and 'symbol' in col.lower()), None)
                        industry_col = next((col for col in reader.fieldnames if col and 'industry' in col.lower()), None)
                        if symbol_col and industry_col:
                            for row in reader:
                                sym = row.get(symbol_col, "").strip()
                                ind = row.get(industry_col, "").strip()
                                if sym and ind:
                                    mapping[sym] = ind
            except Exception as e:
                logger.error(f"Error reading industry from Nifty_500.csv: {e}")
        return mapping

    def get_symbol_sectors(self) -> Dict[str, str]:
        sectors = self.get_symbol_industries()
        broad_indices = [
            "Nifty_50.csv", "Nifty_Next_50.csv", "Nifty_100.csv", "Nifty_200.csv", 
            "Nifty_Total_Market.csv", "Nifty_500.csv", "Nifty500_Multicap_50:25:25.csv", 
            "Nifty500_LargeMidSmall_Equal-Cap_Weighted.csv", "Nifty_Midcap_150.csv", 
            "Nifty_Midcap_50.csv", "Nifty_Midcap_100.csv", "Nifty_Smallcap_250.csv", 
            "Nifty_Smallcap_50.csv", "Nifty_Smallcap_100.csv", "Nifty_Microcap_250.csv", 
            "Nifty_LargeMidcap_250.csv", "Nifty_MidSmallcap_400.csv", 
            "Nifty_MidSmallcap400_50:50.csv", "Nifty_India_FPI_150.csv", 
            "Nifty_Midcap_Select.csv"
        ]
        try:
            for file in os.listdir(self.data_dir):
                if file.endswith(".csv") and file not in broad_indices and file != "archive":
                    name = file.replace(".csv", "").replace("_", " ").replace("Nifty ", "").replace("NIFTY ", "")
                    file_path = os.path.join(self.data_dir, file)
                    try:
                        with open(file_path, "r", encoding="utf-8-sig") as f:
                            reader = csv.DictReader(f)
                            if reader.fieldnames:
                                symbol_col = next((col for col in reader.fieldnames if col and 'symbol' in col.lower()), None)
                                if symbol_col:
                                    for row in reader:
                                        sym = row.get(symbol_col, "").strip()
                                        if sym:
                                            if sym not in sectors:
                                                sectors[sym] = name
                                            elif name.lower() not in sectors[sym].lower():
                                                sectors[sym] = f"{sectors[sym]} ({name})"
                    except Exception as e:
                        logger.error(f"Error mapping sector from {file}: {e}")
        except Exception as e:
            logger.error(f"Error listing data dir for sectors: {e}")
        return sectors
