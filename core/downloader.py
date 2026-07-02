import httpx
import logging
from typing import AsyncGenerator, Dict, Any, Optional, Tuple

logger = logging.getLogger("ZohalDownloader")

class HTTPDownloader:
    @classmethod
    async def get_stream(
        cls,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        proxy_config: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Tuple[bytes, int, str], None]:
        """
        Connects to a URL and yields chunks of bytes, along with total size and content-type.
        Supports proxy, redirects, and custom headers.
        
        Yields:
            (chunk: bytes, total_size: int, content_type: str)
        """
        # Formulate proxy URL for httpx if enabled
        proxy_url = None
        if proxy_config and proxy_config.get("scheme") and proxy_config.get("hostname"):
            scheme = proxy_config["scheme"]
            host = proxy_config["hostname"]
            port = proxy_config["port"]
            user = proxy_config.get("username")
            pwd = proxy_config.get("password")
            
            auth_str = f"{user}:{pwd}@" if user and pwd else ""
            proxy_url = f"{scheme}://{auth_str}{host}:{port}"

        client_args = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(30.0, read=300.0),
            "trust_env": False,
        }
        if proxy_url:
            client_args["proxy"] = proxy_url

        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient(**client_args) as client:
            async with client.stream("GET", url, headers=req_headers) as response:
                if response.status_code >= 400:
                    raise Exception(f"HTTP Error {response.status_code}: {response.reason_phrase}")

                content_length = response.headers.get("content-length")
                total_size = int(content_length) if content_length else 0
                content_type = response.headers.get("content-type", "application/octet-stream")

                # Stream chunks of 128KB
                async for chunk in response.iter_bytes(chunk_size=128 * 1024):
                    yield chunk, total_size, content_type

    @classmethod
    async def get_file_info(
        cls,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        proxy_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Sends a HEAD/GET request to fetch file metadata (name, size, content type) without downloading.
        """
        proxy_url = None
        if proxy_config and proxy_config.get("scheme") and proxy_config.get("hostname"):
            scheme = proxy_config["scheme"]
            host = proxy_config["hostname"]
            port = proxy_config["port"]
            user = proxy_config.get("username")
            pwd = proxy_config.get("password")
            
            auth_str = f"{user}:{pwd}@" if user and pwd else ""
            proxy_url = f"{scheme}://{auth_str}{host}:{port}"

        client_args = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(15.0),
            "trust_env": False,
        }
        if proxy_url:
            client_args["proxy"] = proxy_url

        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient(**client_args) as client:
            # Try HEAD first
            try:
                response = await client.head(url, headers=req_headers)
                if response.status_code == 405: # Method not allowed, retry with GET
                    response = await client.get(url, headers=req_headers)
            except Exception:
                response = await client.get(url, headers=req_headers)

            if response.status_code >= 400:
                raise Exception(f"HTTP Error {response.status_code}")

            content_length = response.headers.get("content-length")
            total_size = int(content_length) if content_length else 0
            content_type = response.headers.get("content-type", "application/octet-stream")
            
            # Extract filename from Content-Disposition or URL
            filename = "file"
            cd = response.headers.get("content-disposition", "")
            if "filename=" in cd:
                parts = cd.split("filename=")
                if len(parts) > 1:
                    filename = parts[1].strip('"').strip("'")
            else:
                # Extract from URL path
                path = url.split("?")[0]
                filename = path.split("/")[-1]
                if not filename:
                    filename = "downloaded_file"

            return {
                "filename": filename,
                "size": total_size,
                "content_type": content_type
            }
