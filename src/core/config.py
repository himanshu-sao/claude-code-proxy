import os
import time
import sys
import itertools
from src.core.client import OpenAIClient

# Configuration
class Config:
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        # Add Anthropic API key for client validation
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            print("Warning: ANTHROPIC_API_KEY not set. Client API key validation will be disabled.")
        
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.azure_api_version = os.environ.get("AZURE_API_VERSION")  # For Azure OpenAI
        self.host = os.environ.get("HOST", "0.0.0.0")
        self.port = int(os.environ.get("PORT", "8082"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        self.max_tokens_limit = int(os.environ.get("MAX_TOKENS_LIMIT", "4096"))
        self.min_tokens_limit = int(os.environ.get("MIN_TOKENS_LIMIT", "100"))

        # --- Multi‑provider support via OPENAI_API_KEY (comma‑separated) ---
        # If OPENAI_API_KEY contains commas, treat each as a separate key sharing the same base URL.
        if self.openai_api_key and "," in self.openai_api_key:
            keys = [k.strip() for k in self.openai_api_key.split(",") if k.strip()]
            self.providers = [{"api_key": k, "base_url": self.openai_base_url} for k in keys]
        else:
            # Fallback to single provider configuration
            self.providers = [{"api_key": self.openai_api_key, "base_url": self.openai_base_url}]

        # Round‑robin iterator over providers
        self._provider_cycle = itertools.cycle(self.providers)

        # Usage tracking for RPM limits
        self._provider_usage = {p["api_key"]: {"count": 0, "window_start": time.time()} for p in self.providers}
        self._rpm_limit = 40  # Default RPM limit per key

        # Connection settings
        self.request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "90"))
        self.max_retries = int(os.environ.get("MAX_RETRIES", "2"))
        
        # Model settings - BIG and SMALL models
        self.big_model = os.environ.get("BIG_MODEL", "gpt-4o")
        self.middle_model = os.environ.get("MIDDLE_MODEL", self.big_model)
        self.small_model = os.environ.get("SMALL_MODEL", "gpt-4o-mini")
        
    def validate_api_key(self):
        """Basic API key validation"""
        if not self.openai_api_key:
            return False
        # Basic format check for OpenAI API keys
        if not self.openai_api_key.startswith('sk-'):
            return False
        return True
        
    def validate_client_api_key(self, client_api_key):
        """Validate client's Anthropic API key"""
        # If no ANTHROPIC_API_KEY is set in environment, skip validation
        if not self.anthropic_api_key:
            return True
            
        # Check if the client's API key matches the expected value
        return client_api_key == self.anthropic_api_key
    
    def get_custom_headers(self):
        """Get custom headers from environment variables"""
        custom_headers = {}
        
        # Get all environment variables
        env_vars = dict(os.environ)
        
        # Find CUSTOM_HEADER_* environment variables
        for env_key, env_value in env_vars.items():
            if env_key.startswith('CUSTOM_HEADER_'):
                # Convert CUSTOM_HEADER_KEY to Header-Key
                # Remove 'CUSTOM_HEADER_' prefix and convert to header format
                header_name = env_key[14:]  # Remove 'CUSTOM_HEADER_' prefix
                
                if header_name:  # Make sure it's not empty
                    # Convert underscores to hyphens for HTTP header format
                    header_name = header_name.replace('_', '-')
                    custom_headers[header_name] = env_value
        
        return custom_headers

    def get_next_provider(self):
        """Return the next provider configuration respecting RPM limits.
        Each provider can be used up to 40 times per minute. If a provider has
        exhausted its quota, the method skips it and checks the next one. If all
        providers are exhausted, it raises a RuntimeError indicating the need
        to wait before making more requests.
        """
        # Clean up usage windows that have expired
        now = time.time()
        for api_key, usage in self._provider_usage.items():
            if now - usage["window_start"] >= 60:
                usage["count"] = 0
                usage["window_start"] = now
        # Attempt to find a provider with remaining quota
        for _ in range(len(self.providers)):
            provider = next(self._provider_cycle)
            usage = self._provider_usage[provider["api_key"]]
            if usage["count"] < self._rpm_limit:
                # Increment usage for this selection
                usage["count"] += 1
                return provider
        # All providers exhausted
        raise RuntimeError("All API keys have reached their RPM limit. Wait before retrying.")

    def get_next_client(self):
        """Create an OpenAIClient for the next provider.
        This is used per request so that each request can use a different API key.
        If all API keys have reached their RPM limit, the method waits until the
        next minute window opens and logs a message.
        """
        try:
            prov = self.get_next_provider()
        except RuntimeError as e:
            # All keys exhausted – calculate wait time until the next minute window
            now = time.time()
            # Find the smallest time remaining until a window resets
            wait_times = []
            for usage in self._provider_usage.values():
                elapsed = now - usage["window_start"]
                remaining = max(0, 60 - elapsed)
                wait_times.append(remaining)
            wait = min(wait_times) if wait_times else 60
            print(f"⚠️ All API keys exhausted. Waiting {int(wait)} seconds before retrying.")
            time.sleep(wait)
            # After waiting, retry once
            prov = self.get_next_provider()
        custom_headers = self.get_custom_headers()
        return OpenAIClient(
            api_key=prov["api_key"],
            base_url=prov["base_url"],
            timeout=self.request_timeout,
            api_version=self.azure_api_version,
            custom_headers=custom_headers,
        )

try:
    config = Config()
    print(f" Configuration loaded: API_KEY={'*' * 20}..., BASE_URL='{config.openai_base_url}'")
except Exception as e:
    print(f"=4 Configuration Error: {e}")
    sys.exit(1)
