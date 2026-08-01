import os
import gzip
import json
import httpx
import logging
from typing import Dict, Any, Optional, List

from src.managers.auth_manager import AuthManager

logger = logging.getLogger(__name__)

class InstrumentManager:
    """
    Service for interacting with Upstox Instrument APIs.
    """

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self.base_url = "https://api.upstox.com/v2"
        self.assets_url = "https://assets.upstox.com/market-quote/instruments/exchange"
        
        # Ensure data directory exists
        self.data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(self.data_dir, exist_ok=True)

    async def search_instruments(self, query: str, expiry: str = None, 
                                 atm_offset: int = None, page_number: int = 1, 
                                 records: int = 20) -> Dict[str, Any]:
        """
        Search for instruments using the V2 API.
        Requires authentication.
        """
        if not self.auth_manager.is_token_valid():
            raise ValueError("Not authenticated with Upstox")

        url = f"{self.base_url}/instruments/search"
        
        params = {
            "query": query,
            "page_number": page_number,
            "records": records
        }
        
        if expiry:
            params["expiry"] = expiry
        if atm_offset is not None:
            params["atm_offset"] = atm_offset

        headers = self.auth_manager.get_headers()

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Search failed: {response.text}")
                return {"error": "Failed to search instruments", "details": response.text}

    async def download_instrument_file(self, file_type: str = "complete") -> str:
        """
        Download the full instrument JSON.gz file from Upstox assets.
        No authentication required for assets.upstox.com.
        Valid file_types: complete, NSE, BSE, MCX, mf-instruments, MTF, NSE_MIS
        """
        url = f"{self.assets_url}/{file_type}.json.gz"
        file_path = os.path.join(self.data_dir, f"{file_type}.json.gz")
        json_path = os.path.join(self.data_dir, f"{file_type}.json")

        logger.info(f"Downloading instrument file from {url}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                # Save the .gz file
                with open(file_path, "wb") as f:
                    f.write(response.content)
                
                # Decompress and process
                try:
                    with gzip.open(file_path, "rb") as gz_file:
                        decompressed_data = gz_file.read()
                    
                    if file_type == "complete":
                        # Parse and extract only equities and indices (approx 2% of the file)
                        all_instruments = json.loads(decompressed_data.decode('utf-8'))
                        filtered = [
                            inst for inst in all_instruments
                            if (inst.get('segment') in ['NSE_EQ', 'BSE_EQ'] and inst.get('instrument_type') == 'EQ') or
                               (inst.get('segment') == 'NSE_INDEX' and inst.get('instrument_type') == 'INDEX')
                        ]
                        master_path = os.path.join(self.data_dir, "equities_master.json")
                        with open(master_path, "w", encoding="utf-8") as f_out:
                            json.dump(filtered, f_out)
                        
                        logger.info(f"Extracted {len(filtered)} equities/indices from master file and saved to equities_master.json")
                        
                        # Clean up the large files
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        if os.path.exists(json_path):
                            os.remove(json_path)
                            
                        return master_path
                    else:
                        with open(json_path, "wb") as uncompressed_file:
                            uncompressed_file.write(decompressed_data)
                        return json_path
                except Exception as e:
                    logger.error(f"Failed to process downloaded file: {e}")
                    return file_path
            else:
                logger.error(f"Failed to download instruments file: {response.status_code}")
                raise Exception(f"Download failed with status {response.status_code}")
