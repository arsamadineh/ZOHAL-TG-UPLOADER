import os
import json
import asyncio
from typing import Dict, Any, Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "telegram_api_id": "",
    "telegram_api_hash": "",
    "telegram_bot_token": "",
    "proxy_type": "none", # none, socks5, http, https
    "proxy_host": "",
    "proxy_port": 0,
    "proxy_username": "",
    "proxy_password": "",
    "s3_endpoint": "",
    "s3_access_key": "",
    "s3_secret_key": "",
    "s3_bucket": "",
    "s3_region": "us-east-1",
    "s3_provider": "custom", # aws, cloudflare, minio, arvan, custom
    "owner_id": 0,
    "web_password": "",
    "web_port": 7531,
    "setup_completed": False,
    "chunk_size_mb": 10,
    "upload_speed_limit_kb": 0, # 0 means unlimited
    "webhook_enabled": False,
    "webhook_url": "",
    "channel_id": "",
    "allowed_extensions": []
}

class ConfigManager:
    _lock = asyncio.Lock()
    _cached_config: Dict[str, Any] = {}

    @classmethod
    def load(cls) -> Dict[str, Any]:
        """Synchronously load config, used at initial startup before loop is running."""
        if cls._cached_config:
            return cls._cached_config
        
        if not os.path.exists(CONFIG_PATH):
            cls._cached_config = DEFAULT_CONFIG.copy()
            cls.save_sync(cls._cached_config)
            return cls._cached_config

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Merge with default config to ensure all keys exist
                cls._cached_config = {**DEFAULT_CONFIG, **data}
                return cls._cached_config
        except Exception:
            cls._cached_config = DEFAULT_CONFIG.copy()
            return cls._cached_config

    @classmethod
    async def get_config(cls) -> Dict[str, Any]:
        async with cls._lock:
            if not cls._cached_config:
                cls.load()
            return cls._cached_config

    @classmethod
    async def get(cls, key: str, default: Any = None) -> Any:
        config = await cls.get_config()
        return config.get(key, default)

    @classmethod
    def save_sync(cls, config_data: Dict[str, Any]):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    @classmethod
    async def update(cls, updates: Dict[str, Any]) -> Dict[str, Any]:
        async with cls._lock:
            config = cls.load()
            for k, v in updates.items():
                if k in DEFAULT_CONFIG:
                    # Type conversion
                    if isinstance(DEFAULT_CONFIG[k], bool):
                        config[k] = bool(v)
                    elif isinstance(DEFAULT_CONFIG[k], int):
                        config[k] = int(v) if v else 0
                    elif isinstance(DEFAULT_CONFIG[k], list):
                        config[k] = list(v) if isinstance(v, list) else [x.strip() for x in str(v).split(",") if x.strip()]
                    else:
                        config[k] = str(v)
            
            cls._cached_config = config
            # Write in background executor to avoid blocking
            await asyncio.to_thread(cls.save_sync, config)
            return config

    @classmethod
    def get_pyrogram_proxy(cls) -> Optional[Dict[str, Any]]:
        """Get Pyrogram-compatible proxy dictionary."""
        config = cls.load()
        p_type = config.get("proxy_type", "none").lower()
        if p_type == "none" or not config.get("proxy_host"):
            return None
        
        # Mapping standard proxy names to pyrogram schemas
        # Pyrogram expects: dict(scheme="socks5", hostname="1.2.3.4", port=1080, username="user", password="pwd")
        scheme = "socks5" if "socks5" in p_type else "http"
        
        proxy = {
            "scheme": scheme,
            "hostname": config.get("proxy_host"),
            "port": int(config.get("proxy_port", 1080)),
        }
        if config.get("proxy_username"):
            proxy["username"] = config.get("proxy_username")
        if config.get("proxy_password"):
            proxy["password"] = config.get("proxy_password")
            
        return proxy

    @classmethod
    async def get_active_pyrogram_proxy(cls) -> Optional[Dict[str, Any]]:
        """Get the active proxy from database if selected, else fallback to config."""
        try:
            from database.db import Database
            active_proxy = await Database.get_active_proxy()
            if active_proxy:
                p_type = active_proxy.get("scheme", "socks5").lower()
                scheme = "socks5" if "socks5" in p_type else "http"
                proxy = {
                    "scheme": scheme,
                    "hostname": active_proxy.get("host"),
                    "port": int(active_proxy.get("port", 1080)),
                }
                if active_proxy.get("username"):
                    proxy["username"] = active_proxy.get("username")
                if active_proxy.get("password"):
                    proxy["password"] = active_proxy.get("password")
                return proxy
        except Exception as e:
            print(f"Error getting active proxy from database: {e}")
        
        # Fallback
        return cls.get_pyrogram_proxy()
