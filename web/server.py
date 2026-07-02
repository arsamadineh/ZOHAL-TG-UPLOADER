import os
import time
import asyncio
import logging
from typing import Optional, Set
from fastapi import FastAPI, Request, Response, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import psutil
import httpx

from core.config import ConfigManager
from core.s3 import S3Client
from core.downloader import HTTPDownloader
from core.manager import TaskManager
from database.db import Database
from bot.bot import BotService

logger = logging.getLogger("ZohalWebServer")

# Custom logging handler to stream logs to WebUI via WebSockets
class WSLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.active_connections: Set[WebSocket] = set()

    def emit(self, record):
        log_msg = self.format(record)
        # Dispatch to all websocket tasks
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
            
        if loop and loop.is_running():
            for ws in list(self.active_connections):
                loop.create_task(self.safe_send(ws, log_msg))

    async def safe_send(self, ws: WebSocket, msg: str):
        try:
            await ws.send_text(msg)
        except Exception:
            self.active_connections.discard(ws)

# Initialize FastAPI App
app = FastAPI(title="Zohal Uploader Panel")

# Setup WebSockets Log Interceptor
ws_log_handler = WSLogHandler()
ws_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(ws_log_handler)

# Templates & Static folders setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Helpers for authentication
def is_authenticated(request: Request) -> bool:
    config = ConfigManager.load()
    pwd = config.get("web_password")
    # Simple session token cookie checking
    cookie = request.cookies.get("zohal_session")
    return cookie == str(hash(pwd))

def check_login_redirect(request: Request):
    config = ConfigManager.load()
    if not config.get("setup_completed"):
        return RedirectResponse(url="/setup", status_code=303)
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return None

# Pydantic models for API validation
class SetupData(BaseModel):
    telegram_api_id: str
    telegram_api_hash: str
    telegram_bot_token: str
    proxy_type: str
    proxy_host: str
    proxy_port: int
    proxy_username: str
    proxy_password: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str
    s3_provider: str
    owner_id: int
    web_password: str

class UserAddData(BaseModel):
    user_id: int
    username: str
    first_name: str
    is_admin: bool = False

class ProxyAddData(BaseModel):
    name: str
    scheme: str
    host: str
    port: int
    username: Optional[str] = ""
    password: Optional[str] = ""

class RenameData(BaseModel):
    old_key: str
    new_key: str

class ShareData(BaseModel):
    key: str
    expiry: int

class DeleteData(BaseModel):
    key: str

# HTML Routes
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    config = await ConfigManager.get_config()
    if not config.get("setup_completed"):
        return RedirectResponse(url="/setup")
    if not is_authenticated(request):
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/dashboard")

@app.get("/setup", response_class=HTMLResponse)
async def setup_route(request: Request):
    config = await ConfigManager.get_config()
    if config.get("setup_completed"):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request=request, name="setup.html", context={"config": config})

@app.get("/login", response_class=HTMLResponse)
async def login_route(request: Request):
    config = await ConfigManager.get_config()
    if not config.get("setup_completed"):
        return RedirectResponse(url="/setup")
    if is_authenticated(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
async def login_post(request: Request, response: Response):
    form = await request.form()
    password = form.get("password")
    config = await ConfigManager.get_config()
    
    if password == config.get("web_password"):
        hashed = str(hash(password))
        response = RedirectResponse(url="/dashboard", status_code=303)
        # Expire in 7 days
        response.set_cookie(key="zohal_session", value=hashed, max_age=7*24*60*60)
        return response
        
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "رمز عبور نادرست است."})

@app.get("/logout")
async def logout_route(response: Response):
    response = RedirectResponse(url="/login")
    response.delete_cookie("zohal_session")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_route(request: Request):
    redirect = check_login_redirect(request)
    if redirect:
        return redirect
    config = await ConfigManager.get_config()
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"config": config})

# WebSocket Logs endpoint
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    ws_log_handler.active_connections.add(websocket)
    try:
        while True:
            # Keep socket open and process incoming pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_log_handler.active_connections.discard(websocket)

# API Endpoints
@app.post("/api/setup/test-telegram")
async def test_telegram_api(data: SetupData):
    # Setup temporary proxy
    p_type = data.proxy_type.lower()
    proxy = None
    if p_type != "none" and data.proxy_host:
        scheme = "socks5" if "socks5" in p_type else "http"
        proxy = {
            "scheme": scheme,
            "hostname": data.proxy_host,
            "port": data.proxy_port,
        }
        if data.proxy_username:
            proxy["username"] = data.proxy_username
        if data.proxy_password:
            proxy["password"] = data.proxy_password
            
    # Try HTTP requests to api.telegram.org to check proxy and network status
    url = f"https://api.telegram.org/bot{data.telegram_bot_token}/getMe"
    proxy_url = None
    if proxy:
        auth = f"{proxy['username']}:{proxy['password']}@" if proxy.get("username") else ""
        proxy_url = f"{proxy['scheme']}://{auth}{proxy['hostname']}:{proxy['port']}"
        
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10.0,
            trust_env=False
        ) as client:
            res = await client.get(url)
            if res.status_code == 200:
                body = res.json()
                if body.get("ok"):
                    bot_name = body["result"]["first_name"]
                    return {"status": "success", "message": f"اتصال برقرار شد! بات یافت شد: {bot_name}"}
            return {"status": "error", "message": f"خطای تلگرام: {res.text}"}
    except Exception as e:
        return {"status": "error", "message": f"اتصال ناموفق: {str(e)}"}

@app.post("/api/setup/test-s3")
async def test_s3_api(data: SetupData):
    try:
        s3 = S3Client({
            "s3_endpoint": data.s3_endpoint,
            "s3_access_key": data.s3_access_key,
            "s3_secret_key": data.s3_secret_key,
            "s3_bucket": data.s3_bucket,
            "s3_region": data.s3_region,
            "s3_provider": data.s3_provider
        })
        success = await s3.test_connection()
        if success:
            return {"status": "success", "message": "ارتباط با موفقیت به S3 برقرار شد!"}
        return {"status": "error", "message": "اتصال به S3 ناموفق بود. دسترسی‌ها را کنترل کنید."}
    except Exception as e:
        return {"status": "error", "message": f"خطا: {str(e)}"}

@app.post("/api/setup/save")
async def save_setup_api(data: SetupData):
    config_dict = data.model_dump()
    config_dict["setup_completed"] = True
    
    await ConfigManager.update(config_dict)
    
    # Fire up the database tables
    await Database.init_db()
    
    # Start the bot client
    started = await BotService.start()
    
    if started:
        return {"status": "success", "message": "پیکربندی ذخیره و ربات با موفقیت فعال شد!"}
    else:
        return {"status": "warning", "message": "پیکربندی ذخیره شد اما راه‌اندازی ربات ناموفق بود. لاگ‌ها را بررسی کنید."}

# Authenticated APIs
@app.get("/api/stats")
async def get_system_stats(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    
    # Network bandwidth delta
    net_1 = psutil.net_io_counters()
    await asyncio.sleep(0.5)
    net_2 = psutil.net_io_counters()
    
    net_speed_in = (net_2.bytes_recv - net_1.bytes_recv) * 2
    net_speed_out = (net_2.bytes_sent - net_1.bytes_sent) * 2
    
    db_stats = await Database.get_upload_stats()
    queue = await TaskManager.get_active_tasks()
    
    return {
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "net_in": net_speed_in,
        "net_out": net_speed_out,
        "uploads": db_stats,
        "queue": queue,
        "bot_running": BotService.is_running()
    }

@app.get("/api/users")
async def get_users_api(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    users = await Database.get_users()
    return users

@app.post("/api/users/add")
async def add_user_api(request: Request, data: UserAddData):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    success = await Database.add_user(data.user_id, data.username, data.first_name, data.is_admin)
    return {"status": "success" if success else "error"}

@app.post("/api/users/delete/{user_id}")
async def delete_user_api(request: Request, user_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    config = await ConfigManager.get_config()
    if user_id == int(config.get("owner_id", 0)):
        return {"status": "error", "message": "نمی‌توان مالک ربات را حذف کرد."}
        
    success = await Database.remove_user(user_id)
    return {"status": "success" if success else "error"}

@app.get("/api/s3/files")
async def get_s3_files_api(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    config = await ConfigManager.get_config()
    s3 = S3Client(config)
    files = await s3.list_files()
    return files

@app.post("/api/s3/delete")
async def delete_s3_file_api(request: Request, data: DeleteData):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    config = await ConfigManager.get_config()
    s3 = S3Client(config)
    success = await s3.delete_file(data.key)
    return {"status": "success" if success else "error"}

@app.post("/api/s3/rename")
async def rename_s3_file_api(request: Request, data: RenameData):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    config = await ConfigManager.get_config()
    s3 = S3Client(config)
    success = await s3.rename_file(data.old_key, data.new_key)
    return {"status": "success" if success else "error"}

@app.post("/api/s3/share")
async def share_s3_file_api(request: Request, data: ShareData):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    config = await ConfigManager.get_config()
    s3 = S3Client(config)
    url = await s3.generate_share_link(data.key, data.expiry)
    return {"status": "success", "url": url}

@app.post("/api/settings/update")
async def update_settings_api(request: Request, data: dict):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    # Exclude setup_completed unless explicitly set
    updated = await ConfigManager.update(data)
    
    # Restart bot in background to apply modifications
    asyncio.create_task(BotService.restart())
    return {"status": "success", "config": updated}

@app.get("/api/queue/cancel/{task_id}")
async def cancel_task_api(request: Request, task_id: str):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    success = await TaskManager.cancel_task(task_id)
    return {"status": "success" if success else "error"}

@app.get("/api/proxies")
async def get_proxies_api(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await Database.get_proxies()

@app.post("/api/proxies/add")
async def add_proxy_api(request: Request, data: ProxyAddData):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    success = await Database.add_proxy(
        name=data.name,
        scheme=data.scheme,
        host=data.host,
        port=data.port,
        username=data.username,
        password=data.password
    )
    return {"status": "success" if success else "error"}

@app.post("/api/proxies/delete/{proxy_id}")
async def delete_proxy_api(request: Request, proxy_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    success = await Database.delete_proxy(proxy_id)
    return {"status": "success" if success else "error"}

@app.post("/api/proxies/select")
async def select_proxy_api(request: Request, data: dict):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    proxy_id = data.get("proxy_id")
    success = await Database.set_active_proxy(proxy_id)
    # Restart bot service asynchronously to apply new proxy configuration immediately
    asyncio.create_task(BotService.restart())
    return {"status": "success" if success else "error"}

@app.post("/api/proxies/test/{proxy_id}")
async def test_single_proxy_api(request: Request, proxy_id: int):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    proxy = await Database.get_proxy_by_id(proxy_id)
    if not proxy:
        return {"status": "error", "message": "پروکسی یافت نشد."}
        
    from core.proxy import ProxyTester
    # Test proxy
    proxy_config = {
        "scheme": proxy["scheme"],
        "hostname": proxy["host"],
        "port": proxy["port"],
        "username": proxy["username"],
        "password": proxy["password"]
    }
    
    result = await ProxyTester.test_proxy(proxy_config)
    if result["status"] == "success":
        await Database.update_proxy_test_result(
            proxy_id=proxy_id,
            status="success",
            latency=result["latency_ms"],
            country=result["country"],
            country_code=result["country_code"]
        )
    else:
        await Database.update_proxy_test_result(
            proxy_id=proxy_id,
            status="error",
            latency=-1,
            country="خطا",
            country_code="ERR"
        )
        
    return result
