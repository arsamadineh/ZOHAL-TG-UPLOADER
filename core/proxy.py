import time
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("ZohalProxyTester")

class ProxyTester:
    @classmethod
    async def test_proxy(cls, proxy_config: dict) -> dict:
        """
        Tests SOCKS5/HTTP/HTTPS proxy connection.
        Measures latency and fetches country details using a geolocation API.
        Attempts multiple API targets for failover resilience.
        """
        scheme = proxy_config.get("scheme", "socks5")
        host = proxy_config.get("hostname")
        port = proxy_config.get("port")
        user = proxy_config.get("username")
        pwd = proxy_config.get("password")
        
        if not host or not port:
            return {"status": "error", "message": "Missing host or port"}

        auth_str = f"{user}:{pwd}@" if user and pwd else ""
        proxy_url = f"{scheme}://{auth_str}{host}:{port}"
        
        # Geolocation API targets with response field mappings
        targets = [
            {
                "url": "https://freeipapi.com/api/json",
                "ip_field": "ipAddress",
                "country_field": "countryName",
                "country_code_field": "countryCode",
                "city_field": "cityName",
                "org_field": None
            },
            {
                "url": "https://ipapi.co/json/",
                "ip_field": "ip",
                "country_field": "country_name",
                "country_code_field": "country_code",
                "city_field": "city",
                "org_field": "org"
            },
            {
                "url": "http://ip-api.com/json/",
                "ip_field": "query",
                "country_field": "country",
                "country_code_field": "countryCode",
                "city_field": "city",
                "org_field": "isp"
            }
        ]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        last_error = None
        for target in targets:
            start_time = time.time()
            try:
                async with httpx.AsyncClient(proxy=proxy_url, timeout=10.0, headers=headers, trust_env=False) as client:
                    response = await client.get(target["url"])
                    latency = (time.time() - start_time) * 1000
                    
                    if response.status_code == 200:
                        data = response.json()
                        ip = data.get(target["ip_field"], "Unknown")
                        country = data.get(target["country_field"], "Unknown")
                        country_code = data.get(target["country_code_field"], "Unknown")
                        city = data.get(target["city_field"], "Unknown")
                        org = data.get(target["org_field"], "Unknown") if target["org_field"] else "Unknown"
                        
                        return {
                            "status": "success",
                            "latency_ms": round(latency, 1),
                            "ip": ip,
                            "country": country,
                            "country_code": country_code,
                            "city": city,
                            "org": org
                        }
                    else:
                        last_error = f"HTTP Error {response.status_code} from {target['url']}"
            except Exception as e:
                logger.warning(f"Proxy test target {target['url']} failed: {e}")
                last_error = str(e)
                continue
                
        logger.error(f"Proxy test failed for {proxy_url}: {last_error}")
        return {
            "status": "error",
            "message": last_error or "All test targets failed"
        }
