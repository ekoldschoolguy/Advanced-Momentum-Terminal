import os
import time
import json
import secrets
import httpx
import logging
from typing import Dict, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class AuthManager:
    """
    Handles Upstox OAuth 2.0 authentication flow
    Uses .env for API credentials and token.json for token storage
    """

    def __init__(self, env_file=".env", token_file="token.json"):
        """Initialize authentication manager"""
        self.base_url = "https://api.upstox.com/v2"
        self.env_file = env_file
        self.token_file = token_file
        
        load_dotenv(self.env_file)
        
        self.api_key = os.getenv("UPSTOX_API_ID")
        self.api_secret = os.getenv("UPSTOX_API_SECRET")
        self.redirect_uri = os.getenv("REDIRECT_URI", "http://127.0.0.1:8000/callback")
        
        self.access_token = None
        self.token_expiry = None
        
        self._load_token()

    def _load_token(self) -> bool:
        """Load token from token.json file"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.token_expiry = data.get("token_expiry")
                return True
            except Exception as e:
                logger.error(f"Failed to load token file: {e}")
        return False

    def _save_token(self, access_token: str, expires_in: int = 86400) -> bool:
        """Save token to token.json file"""
        self.access_token = access_token
        self.token_expiry = time.time() + expires_in - 300  # 5 min buffer
        
        try:
            with open(self.token_file, "w") as f:
                json.dump({
                    "access_token": self.access_token,
                    "token_expiry": self.token_expiry
                }, f)
            return True
        except Exception as e:
            logger.error(f"Failed to save token file: {e}")
            return False

    def has_credentials(self) -> bool:
        """Check if API credentials are configured"""
        return bool(self.api_key and self.api_secret and self.redirect_uri)

    def is_token_valid(self) -> bool:
        """Check if current token is valid"""
        if not self.access_token:
            return False

        if self.token_expiry and time.time() >= self.token_expiry:
            return False

        return True

    def get_authorization_url(self) -> str:
        """
        Generate OAuth authorization URL
        """
        if not self.has_credentials():
            raise ValueError("API credentials not configured in .env.")

        # From V02: state = secrets.token_urlsafe(32)
        params = {
            'client_id': self.api_key,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'state': secrets.token_urlsafe(32)
        }

        # urlencode manually for dict
        from urllib.parse import urlencode
        auth_url = f"{self.base_url}/login/authorization/dialog?{urlencode(params)}"
        return auth_url

    async def exchange_code_for_token(self, auth_code: str) -> bool:
        """
        Exchange authorization code for access token using httpx
        """
        if not self.has_credentials():
            raise ValueError("API credentials not configured in .env")

        url = f"{self.base_url}/login/authorization/token"

        data = {
            'code': auth_code,
            'client_id': self.api_key,
            'client_secret': self.api_secret,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'authorization_code'
        }

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data, headers=headers)

                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get('access_token')
                    expires_in = token_data.get('expires_in', 86400) # Defaults to 1 day
                    
                    self._save_token(access_token, expires_in)
                    logger.info("Successfully obtained access token")
                    return True
                else:
                    logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}")
            return False

    def get_headers(self) -> Dict[str, str]:
        """
        Get headers with authentication token
        """
        self._load_token()

        if not self.is_token_valid():
            raise ValueError("Invalid or expired token. Please authenticate first.")

        return {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def clear_tokens(self) -> None:
        """Clear stored tokens"""
        self.access_token = None
        self.token_expiry = None
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
        logger.info("Cleared stored tokens")

