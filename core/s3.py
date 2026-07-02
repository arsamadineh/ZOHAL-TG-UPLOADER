import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
import aioboto3
from botocore.client import Config
from core.config import ConfigManager

logger = logging.getLogger("ZohalS3")

class S3Client:
    def __init__(self, config: Dict[str, Any], proxy_config: Optional[Dict[str, Any]] = None):
        self.endpoint_url = config.get("s3_endpoint")
        self.access_key = config.get("s3_access_key")
        self.secret_key = config.get("s3_secret_key")
        self.bucket = config.get("s3_bucket")
        self.region = config.get("s3_region", "us-east-1")
        self.provider = config.get("s3_provider", "custom")
        self.proxy_config = proxy_config
        
        # Configure connection pooling and timeout optimizations
        self.session = aioboto3.Session()

    def _get_client_args(self) -> Dict[str, Any]:
        """Generate client configuration parameters for boto3 client."""
        proxies = None
        if self.proxy_config and self.proxy_config.get("scheme") and self.proxy_config.get("hostname"):
            scheme = self.proxy_config["scheme"]
            host = self.proxy_config["hostname"]
            port = self.proxy_config["port"]
            user = self.proxy_config.get("username")
            pwd = self.proxy_config.get("password")
            auth_str = f"{user}:{pwd}@" if user and pwd else ""
            proxy_url = f"http://{auth_str}{host}:{port}"
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            }

        config_args = {
            "signature_version": "s3v4",
            "retries": {"max_attempts": 5, "mode": "standard"},
            "connect_timeout": 15,
            "read_timeout": 30
        }
        if proxies:
            config_args["proxies"] = proxies

        args = {
            "service_name": "s3",
            "aws_access_key_id": self.access_key,
            "aws_secret_access_key": self.secret_key,
            "region_name": self.region,
            "config": Config(**config_args)
        }
        if self.endpoint_url:
            args["endpoint_url"] = self.endpoint_url
        return args

    async def test_connection(self) -> bool:
        """Verify S3 credentials and bucket accessibility."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                # Try listing objects with MaxKeys=1 to check permissions
                await s3.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
                return True
        except Exception as e:
            logger.error(f"S3 Connection test failed: {e}")
            return False

    async def list_buckets(self) -> List[str]:
        """List all buckets under the credentials."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.list_buckets()
                return [b["Name"] for b in response.get("Buckets", [])]
        except Exception as e:
            logger.error(f"Failed to list S3 buckets: {e}")
            return []

    async def create_bucket(self, bucket_name: str) -> bool:
        """Create a new bucket."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                await s3.create_bucket(Bucket=bucket_name)
                return True
        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            return False

    async def upload_stream(
        self,
        stream: AsyncGenerator[bytes, None],
        key: str,
        content_type: str = "application/octet-stream",
        chunk_size_mb: int = 10,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Uploads a stream to S3 using Multipart upload without writing to VPS disk.
        Optimized for memory efficiency (stores only active chunks in memory).
        """
        chunk_size = chunk_size_mb * 1024 * 1024
        # S3 multipart uploads require parts to be >= 5MB (except the last part)
        if chunk_size < 5 * 1024 * 1024:
            chunk_size = 5 * 1024 * 1024

        async with self.session.client(**self._get_client_args()) as s3:
            # Initiate Multipart Upload
            mp_upload = await s3.create_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                ContentType=content_type
            )
            upload_id = mp_upload["UploadId"]
            parts = []
            part_number = 1
            buffer = bytearray()
            total_uploaded = 0
            
            try:
                async for chunk in stream:
                    buffer.extend(chunk)
                    while len(buffer) >= chunk_size:
                        # Slice exact chunk size
                        part_data = bytes(buffer[:chunk_size])
                        del buffer[:chunk_size]
                        
                        # Upload part
                        part = await s3.upload_part(
                            Bucket=self.bucket,
                            Key=key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=part_data
                        )
                        parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                        total_uploaded += len(part_data)
                        
                        if progress_callback:
                            await progress_callback(total_uploaded)
                            
                        part_number += 1
                
                # Upload remaining buffer if any
                if len(buffer) > 0:
                    part_data = bytes(buffer)
                    part = await s3.upload_part(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=part_data
                    )
                    parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                    total_uploaded += len(part_data)
                    
                    if progress_callback:
                        await progress_callback(total_uploaded)

                # Complete Multipart Upload
                await s3.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts}
                )
                
                # Generate URL
                s3_url = f"{self.endpoint_url}/{self.bucket}/{key}" if self.endpoint_url else f"https://{self.bucket}.s3.amazonaws.com/{key}"
                if "digitaloceanspaces.com" in (self.endpoint_url or ""):
                    s3_url = self.endpoint_url.replace("https://", f"https://{self.bucket}.") + f"/{key}"
                
                return {
                    "status": "success",
                    "key": key,
                    "s3_url": s3_url,
                    "total_uploaded": total_uploaded
                }
                
            except Exception as e:
                logger.error(f"S3 Multipart Upload failed for {key}: {e}")
                # Abort Multipart Upload on failure
                try:
                    await s3.abort_multipart_upload(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id
                    )
                except Exception as abort_err:
                    logger.error(f"Failed to abort multipart upload: {abort_err}")
                raise e

    async def list_files(self, prefix: str = "", max_keys: int = 1000) -> List[Dict[str, Any]]:
        """List files in S3 under a specific prefix (folder)."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,
                    MaxKeys=max_keys
                )
                files = []
                for obj in response.get("Contents", []):
                    # Skip folder objects
                    if obj["Key"].endswith("/"):
                        continue
                    files.append({
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].timestamp(),
                        "etag": obj["ETag"].strip('"')
                    })
                return files
        except Exception as e:
            logger.error(f"Failed to list S3 files: {e}")
            return []

    async def list_dir_contents(self, prefix: str = "") -> dict:
        """
        List subfolders and files in S3 under a specific prefix (folder level).
        Returns a dictionary containing:
        - folders: List of folder paths (strings)
        - files: List of file dictionaries (key, size, last_modified, etag)
        """
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,
                    Delimiter="/"
                )
                
                folders = []
                for p in response.get("CommonPrefixes", []):
                    folders.append(p["Prefix"])
                    
                files = []
                for obj in response.get("Contents", []):
                    key = obj["Key"]
                    # Skip folder placeholder objects (keys ending with /)
                    if key.endswith("/") or key == prefix:
                        continue
                    files.append({
                        "key": key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].timestamp() if "LastModified" in obj else 0,
                        "etag": obj["ETag"].strip('"') if "ETag" in obj else ""
                    })
                    
                folders.sort()
                files.sort(key=lambda x: x["key"])
                
                return {
                    "folders": folders,
                    "files": files
                }
        except Exception as e:
            logger.error(f"Failed to list S3 directory contents for prefix '{prefix}': {e}")
            return {"folders": [], "files": []}

    async def get_file_info(self, key: str) -> Optional[dict]:
        """Get metadata of a single file (size, content type, etag)."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.head_object(Bucket=self.bucket, Key=key)
                return {
                    "size": response.get("ContentLength", 0),
                    "content_type": response.get("ContentType", "application/octet-stream"),
                    "etag": response.get("ETag", "").strip('"'),
                    "last_modified": response.get("LastModified").timestamp() if response.get("LastModified") else 0
                }
        except Exception as e:
            logger.error(f"Failed to get file info for {key}: {e}")
            return None

    async def delete_file(self, key: str) -> bool:
        """Delete a file from S3."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                await s3.delete_object(Bucket=self.bucket, Key=key)
                return True
        except Exception as e:
            logger.error(f"Failed to delete S3 file {key}: {e}")
            return False

    async def rename_file(self, old_key: str, new_key: str) -> bool:
        """Rename a file in S3 by copying it and deleting the old one."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                # Copy object
                copy_source = {"Bucket": self.bucket, "Key": old_key}
                await s3.copy_object(
                    CopySource=copy_source,
                    Bucket=self.bucket,
                    Key=new_key
                )
                # Delete original object
                await s3.delete_object(Bucket=self.bucket, Key=old_key)
                return True
        except Exception as e:
            logger.error(f"Failed to rename file from {old_key} to {new_key}: {e}")
            return False

    async def generate_share_link(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generate a secure pre-signed GET URL for downloading files."""
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                url = await s3.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires_in_seconds
                )
                return url
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL for {key}: {e}")
            return ""

    async def download_stream(self, key: str) -> AsyncGenerator[bytes, None]:
        """Stream file content directly from S3 in chunks."""
        async with self.session.client(**self._get_client_args()) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as body:
                async for chunk in body.iter_chunks(chunk_size=128 * 1024):
                    yield chunk
