import os
import json
import asyncio
from typing import List, Optional
from pathlib import Path
from contextlib import asynccontextmanager

import edge_tts
import aiohttp
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import opencc
except ImportError:
    print("Warning: opencc not installed. Index TTS text conversion may not work.")
    opencc = None

# 配置
PORT = int(os.getenv("PORT", 5456))
BASE_DIR = Path("/app")
VRM_DIR = BASE_DIR / "vrm"
UPLOADS_DIR = BASE_DIR / "uploads"
FRONTEND_DIR = BASE_DIR / "frontend"

# 確保目錄存在
VRM_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

# TTS 隊列系統
class SpeechTask:
    def __init__(self, type: str, data: dict, future: asyncio.Future):
        self.type = type  # "speak" or "stream"
        self.data = data
        self.future = future

speech_queue: asyncio.Queue = asyncio.Queue()
cancel_event: asyncio.Event = asyncio.Event()

# ============= 隊列處理 Worker =============

async def process_speech_queue():
    """背景任務：依序處理語音請求"""
    print("🚀 Speech queue worker started")
    while True:
        try:
            # 等待下一個任務
            task = await speech_queue.get()
            
            # 清除之前的取消信號 (如果有的話)，準備處理新任務
            # 注意：這裡我們不清除，因為如果使用者按了停止，應該連隊列中的都不播
            # 但如果隊列是空的，當新任務來時，應該要重置狀態
            if cancel_event.is_set():
                 # 只有當隊列為空時才重置，或者我們定義 reset 是「清空當前所有」
                 # 簡單策略：每次開始處理新任務前，先檢查是否被取消了
                 # 但這樣會導致 reset 後的新請求無法播放
                 # 正確策略：reset 發生時會清空 queue，所以這裡拿到的 task 肯定是新的
                 cancel_event.clear()

            print(f"📥 Processing speech task: {task.type}")
            
            try:
                if task.type == "speak":
                    # 處理單句 speak
                    req = task.data
                    result = await process_speak_internal(req["text"], req["expression"], req["engine"])
                    if not task.future.done():
                        task.future.set_result(result)
                        
                elif task.type == "stream":
                    # 處理流式 stream-speak
                    req = task.data
                    result = await process_stream_speak_internal(req["text"], req["expression"], req["engine"])
                    if not task.future.done():
                        task.future.set_result(result)
                        
            except Exception as e:
                print(f"❌ Error processing speech task: {e}")
                if not task.future.done():
                    task.future.set_exception(e)
            finally:
                speech_queue.task_done()
                
        except asyncio.CancelledError:
            print("🛑 Speech queue worker stopped")
            break
        except Exception as e:
            print(f"❌ Fatal worker error: {e}")
            await asyncio.sleep(1) # 防止死循環狂刷

# ============= Lifespan (取代 Startup/Shutdown events) =============

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    worker_task = asyncio.create_task(process_speech_queue())
    yield
    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

# FastAPI 應用 (定義在 add_middleware 之前)
app = FastAPI(title="VRM Agent API", lifespan=lifespan)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 連線管理
active_connections: List[WebSocket] = []

# TTS 配置存儲
tts_config = {
    "engine": "edgetts",
    "edgetts": {
        "language": "zh-TW",
        "voice": "HsiaoChenNeural",
        "rate": 1.0
    },
    "indextts": {
        "server_url": "http://10.9.0.35:8001",
        "character": "hayley"
    }
}

# ============= 配置管理函數 =============

def load_config():
    """從文件加載配置"""
    config_file = BASE_DIR / "data" / "vrm_config.json"
    default_config_file = BASE_DIR / "data" / "vrm_config.default.json"
    
    try:
        # 1. 嘗試讀取執行時配置
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                print(f"✅ Config loaded from {config_file}")
                return loaded_config
        
        # 2. 如果不存在，嘗試讀取預設配置
        elif default_config_file.exists():
            with open(default_config_file, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                print(f"ℹ️ Runtime config not found, loaded defaults from {default_config_file}")
                # 可選：自動複製一份變成執行時配置，或者等第一次保存時再建立
                return loaded_config
                
        else:
            print(f"⚠️ No config file found, using hardcoded defaults")
            return None
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return None

def save_config(config_data):
    """保存配置到文件"""
    config_file = BASE_DIR / "data" / "vrm_config.json"
    try:
        config_file.parent.mkdir(exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        print(f"✅ Config saved to {config_file}")
        return True
    except Exception as e:
        print(f"❌ Failed to save config: {e}")
        return False

# ============= Pydantic Models =============

class TTSConfig(BaseModel):
    engine: str
    edgetts: Optional[dict] = None
    indextts: Optional[dict] = None

class SpeakRequest(BaseModel):
    text: str
    expression: Optional[str] = None
    engine: Optional[str] = None

class VRMInfo(BaseModel):
    name: str
    path: str
    type: str  # "default" or "uploaded"

# ============= WebSocket =============

@app.websocket("/ws/vrm")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    print(f"WebSocket connected. Total connections: {len(active_connections)}")
    
    try:
        while True:
            # 保持連線
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print(f"WebSocket disconnected. Total connections: {len(active_connections)}")

async def broadcast_to_vrm(message: dict):
    """廣播訊息到所有 VRM 連線"""
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except:
            disconnected.append(connection)
    
    # 清理斷開的連線
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)

# ============= VRM Management APIs =============

@app.get("/api/vrm/list")
async def list_vrm_models():
    """獲取所有可用的 VRM 模型"""
    models = []
    
    # 預設模型
    if VRM_DIR.exists():
        for vrm_file in VRM_DIR.glob("*.vrm"):
            models.append({
                "name": vrm_file.name,
                "path": f"/vrm/{vrm_file.name}",
                "type": "default"
            })
    
    # 使用者上傳的模型
    if UPLOADS_DIR.exists():
        for vrm_file in UPLOADS_DIR.glob("*.vrm"):
            models.append({
                "name": vrm_file.name,
                "path": f"/uploads/{vrm_file.name}",
                "type": "uploaded"
            })
    
    return {"models": models}

@app.get("/api/vrm/current")
async def get_current_vrm():
    """獲取當前選擇的 VRM"""
    return current_vrm

@app.post("/api/vrm/select")
async def select_vrm(vrm_info: VRMInfo):
    """選擇要使用的 VRM"""
    global current_vrm, vrm_config

    # 更新 current_vrm
    current_vrm = {
        "name": vrm_info.name,
        "path": vrm_info.path
    }

    # 同步更新到 vrm_config
    vrm_config["selectedModelName"] = vrm_info.name
    vrm_config["selectedModelPath"] = vrm_info.path

    # 如果有 model ID，也更新（通過 path 匹配找到對應的 model ID）
    for model in vrm_config["defaultModels"] + vrm_config["userModels"]:
        if model["path"] == vrm_info.path:
            vrm_config["selectedModelId"] = model["id"]
            break

    # 保存到文件（持久化）
    save_config(vrm_config)

    # 通知 VRM 頁面切換模型
    await broadcast_to_vrm({
        "type": "switch_model",
        "data": current_vrm
    })

    print(f"🎭 VRM switched to: {vrm_info.name}")
    return {"success": True, "vrm": current_vrm}

@app.post("/api/vrm/upload")
async def upload_vrm(file: UploadFile = File(...)):
    """上傳 VRM 檔案"""
    global vrm_config

    if not file.filename.endswith('.vrm'):
        raise HTTPException(status_code=400, detail="Only .vrm files are allowed")

    file_path = UPLOADS_DIR / file.filename

    # 保存檔案
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    # 創建新模型對象
    new_model = {
        "id": f"user_{file.filename[:-4]}",  # 移除 .vrm 扩展名
        "name": file.filename,
        "path": f"/uploads/{file.filename}",
        "type": "uploaded"
    }

    # 添加到 userModels 配置（避免重复）
    if not any(m["path"] == new_model["path"] for m in vrm_config["userModels"]):
        vrm_config["userModels"].append(new_model)
        save_config(vrm_config)
        print(f"📦 New VRM model added: {file.filename}")

    return {
        "success": True,
        "vrm": new_model
    }

@app.delete("/api/vrm/delete")
async def delete_vrm(vrm_info: VRMInfo):
    """刪除 VRM 模型"""
    global vrm_config, current_vrm

    # 1. 檢查是否為上傳的模型 (只允許刪除上傳的模型)
    if vrm_info.type != "uploaded":
        raise HTTPException(status_code=400, detail="Cannot delete default models")

    # 2. 查找文件
    file_name = vrm_info.name
    file_path = UPLOADS_DIR / file_name

    if not file_path.exists():
        # 如果文件不存在但配置中有，也應該清理配置
        print(f"⚠️ File not found: {file_path}, cleaning up config anyway")
    else:
        try:
            # 3. 刪除文件
            os.remove(file_path)
            print(f"🗑️ Deleted VRM file: {file_name}")
        except Exception as e:
            print(f"❌ Failed to delete file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

    # 4. 更新配置
    vrm_config["userModels"] = [
        m for m in vrm_config["userModels"] 
        if m["path"] != vrm_info.path
    ]

    # 5. 如果刪除的是當前選中的模型，切換回預設模型
    if current_vrm.get("path") == vrm_info.path:
        default_model = vrm_config["defaultModels"][0]
        current_vrm = {
            "name": default_model["name"],
            "path": default_model["path"]
        }
        vrm_config["selectedModelName"] = default_model["name"]
        vrm_config["selectedModelPath"] = default_model["path"]
        vrm_config["selectedModelId"] = default_model["id"]
        
        # 通知前端切換
        await broadcast_to_vrm({
            "type": "switch_model",
            "data": current_vrm
        })
        print(f"🔄 Switched back to default model: {default_model['name']}")

    save_config(vrm_config)
    return {"success": True, "message": f"Model {file_name} deleted"}

# ============= TTS Configuration APIs =============

@app.get("/api/tts/config")
async def get_tts_config():
    """獲取 TTS 配置"""
    return tts_config

@app.post("/api/tts/config")
async def update_tts_config(config: TTSConfig):
    """更新 TTS 配置"""
    global tts_config
    tts_config["engine"] = config.engine
    if config.edgetts:
        tts_config["edgetts"] = config.edgetts
    if config.indextts:
        tts_config["indextts"] = config.indextts
    return {"success": True, "config": tts_config}

# ============= TTS Speech APIs =============

@app.post("/api/speak")
async def speak(request: SpeakRequest):
    """執行 TTS 語音合成並播放"""
    engine = request.engine or tts_config["engine"]
    text = request.text
    expression = request.expression
    
    # 創建 Future 以等待結果
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    
    # 加入隊列
    task = SpeechTask(
        type="speak",
        data={
            "text": text,
            "expression": expression,
            "engine": engine
        },
        future=future
    )
    await speech_queue.put(task)
    
    # 等待處理完成
    try:
        result = await future
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============= Stream Speak API (Internal Logic Only) =============

def split_text_into_chunks(text: str) -> List[str]:
    """將長文本切割成短句 (比照前端 admin.html 邏輯)"""
    import re
    
    # 1. 文字清理 (比照前端 splitTTSBuffer 邏輯)
    # 移除 Markdown 標題 (#)
    text = re.sub(r'#{1,6}\s', '', text)
    # 移除 Markdown 格式符號 (*_~`)
    text = re.sub(r'[*_~`]+', '', text)
    # 移除列表標記 (- or *)
    text = re.sub(r'^\s*[-*]\s', '', text, flags=re.MULTILINE)
    # 移除圖片 ![alt](url)
    text = re.sub(r'!\\[.*?\\]\(.*?\)', '', text)
    # 移除連結 [text](url) -> text
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # 移除常見 Emoji
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    # 合併多餘空格
    text = re.sub(r'\s+', ' ', text).strip()
    
    if not text:
        return []
        
    # 2. 定義分隔符 (比照前端: "。", "\n", "？", "！", "，", "～", "!", "?", ",", "~")
    # 使用 regex split 並過濾掉空字串
    separators = r'[。\n？！，～!?,~]'
    chunks = [c.strip() for c in re.split(separators, text) if c.strip()]
    
    return chunks

@app.post("/api/stream-speak")
async def stream_speak(request: SpeakRequest):
    """處理長文本，自動分段並依序推播至前端"""
    engine = request.engine or tts_config["engine"]
    text = request.text
    expression = request.expression
    
    # 創建 Future 以等待結果
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    
    # 加入隊列
    task = SpeechTask(
        type="stream",
        data={
            "text": text,
            "expression": expression,
            "engine": engine
        },
        future=future
    )
    await speech_queue.put(task)
    
    # 等待處理完成
    try:
        result = await future
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def process_speak_internal(text, expression, engine):
    """內部使用的 speak 邏輯"""
    print(f"Speaking: {text[:50]}... (engine: {engine})")
    
    # 生成唯一的 chunk ID
    import time
    chunk_id = f"chunk_{int(time.time() * 1000)}"
    
    # 根據引擎生成音訊
    if engine == "edgetts":
        # Edge TTS
        config = tts_config["edgetts"]
        language = config["language"]
        voice = config["voice"]
        rate = config.get("rate", 1.0)
        
        full_voice = f"{language}-{voice}"
        rate_text = f"+{int((rate - 1.0) * 100)}%" if rate >= 1.0 else f"-{int((1.0 - rate) * 100)}%"
        
        # 收集音訊數據
        audio_data = bytearray()
        communicate = edge_tts.Communicate(text, full_voice, rate=rate_text)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        
        # 發送到 WebSocket
        import base64
        audio_base64 = base64.b64encode(bytes(audio_data)).decode('utf-8')
        
        await broadcast_to_vrm({
            "type": "speak",
            "data": {
                "chunkId": chunk_id,
                "text": text,
                "expression": expression,
                "audioData": audio_base64,
                "mimeType": "audio/mpeg"
            }
        })
        
        return {"success": True, "chunkId": chunk_id, "engine": "edgetts"}
        
    elif engine == "indextts":
        # Index TTS
        config = tts_config["indextts"]
        server_url = config["server_url"]
        character = config["character"]
        
        # 繁簡轉換
        processed_text = text
        if opencc:
            try:
                cc = opencc.OpenCC('t2s')
                processed_text = cc.convert(text)
            except:
                pass
        
        # 呼叫 Index TTS API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{server_url}/tts",
                    json={"text": processed_text, "character": character},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        
                        # 發送到 WebSocket
                        import base64
                        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                        
                        await broadcast_to_vrm({
                            "type": "speak",
                            "data": {
                                "chunkId": chunk_id,
                                "text": text,
                                "expression": expression,
                                "audioData": audio_base64,
                                "mimeType": "audio/wav"
                            }
                        })
                        
                        return {"success": True, "chunkId": chunk_id, "engine": "indextts"}
                    else:
                        raise Exception(f"Index TTS error: {response.status}")
        except Exception as e:
            raise Exception(f"Index TTS request failed: {str(e)}")
    
    else:
        raise Exception(f"Unsupported engine: {engine}")

async def process_stream_speak_internal(text, expression, engine):
    """內部使用的 stream-speak 邏輯"""
    import time
    import base64
    
    if not text:
        raise Exception("Text is empty")
        
    # 1. 執行分段
    chunks = split_text_into_chunks(text)
    print(f"🌊 Stream speak: split into {len(chunks)} chunks")
    
    if not chunks:
        return {"success": False, "message": "No valid text content after cleaning"}
        
    # 2. 依序處理每個片段並發送 WebSocket
    for i, chunk in enumerate(chunks):
        # 檢查是否被取消
        if cancel_event.is_set():
            print(f"🛑 Task cancelled, stopping at chunk {i}/{len(chunks)}")
            break

        chunk_id = f"stream_{int(time.time() * 1000)}_{i}"
        print(f"  [Chunk {i+1}/{len(chunks)}] Processing: {chunk[:30]}...")
        
        try:
            if engine == "edgetts":
                # Edge TTS 邏輯
                config = tts_config["edgetts"]
                full_voice = f"{config['language']}-{config['voice']}"
                rate = config.get("rate", 1.0)
                rate_param = f"+{int((rate - 1.0) * 100)}%" if rate >= 1.0 else f"-{int((1.0 - rate) * 100)}%"
                
                audio_data = bytearray()
                communicate = edge_tts.Communicate(chunk, full_voice, rate=rate_param)
                async for chunk_data in communicate.stream():
                    if chunk_data["type"] == "audio":
                        audio_data.extend(chunk_data["data"])
                
                audio_base64 = base64.b64encode(bytes(audio_data)).decode('utf-8')
                mime_type = "audio/mpeg"
                
            elif engine == "indextts":
                # Index TTS 邏輯 (包含繁簡轉換)
                config = tts_config["indextts"]
                processed_text = chunk
                if opencc:
                    try:
                        cc = opencc.OpenCC('t2s')
                        processed_text = cc.convert(chunk)
                        processed_text = processed_text.replace("著", "着")
                        processed_text = processed_text.replace("显着", "显著")
                    except: pass
                print(f"    Processed text for Index TTS: {processed_text[:30]}...")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{config['server_url']}/tts",
                        json={"text": processed_text, "character": config['character']},
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status == 200:
                            audio_bytes = await response.read()
                            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                            mime_type = "audio/wav"
                        else:
                            print(f"  ❌ Chunk {i+1} failed: Index TTS error {response.status}")
                            continue
            else:
                print(f"  ❌ Unsupported engine: {engine}")
                break

            # 將結果推播給前端顯示頁面
            await broadcast_to_vrm({
                "type": "speak",
                "data": {
                    "chunkId": chunk_id,
                    "text": chunk,
                    "expression": expression,
                    "audioData": audio_base64,
                    "mimeType": mime_type
                }
            })
            
        except Exception as e:
            print(f"  ❌ Error processing chunk {i+1}: {str(e)}")
            continue

    return {
        "success": True, 
        "chunks_count": len(chunks),
        "message": "All chunks processed and sent to queue"
    }

# ============= Animation Management APIs =============

@app.get("/api/animations/list")
async def list_animations():
    """獲取所有可用的動畫檔案"""
    animations = []
    
    # 預設動畫
    vrm_animations_dir = VRM_DIR / "animations"
    if vrm_animations_dir.exists():
        for vrma_file in vrm_animations_dir.glob("*.vrma"):
            animations.append({
                "id": vrma_file.stem,
                "name": vrma_file.name,
                "path": f"/vrm/animations/{vrma_file.name}",
                "type": "default"
            })
    
    # 使用者上傳的動畫
    uploads_animations_dir = UPLOADS_DIR / "animations"
    if uploads_animations_dir.exists():
        for vrma_file in uploads_animations_dir.glob("*.vrma"):
            animations.append({
                "id": f"user_{vrma_file.stem}",
                "name": vrma_file.name,
                "path": f"/uploads/animations/{vrma_file.name}",
                "type": "uploaded"
            })
    
    return {"animations": animations}

@app.post("/api/animations/upload")
async def upload_animation(file: UploadFile = File(...)):
    """上傳動畫檔案"""
    global vrm_config

    if not file.filename.endswith('.vrma'):
        raise HTTPException(status_code=400, detail="Only .vrma files are allowed")

    # 確保動畫目錄存在
    animations_dir = UPLOADS_DIR / "animations"
    animations_dir.mkdir(exist_ok=True)

    file_path = animations_dir / file.filename

    # 保存檔案
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    # 創建動畫資訊
    animation_id = f"user_{file.filename[:-5]}"  # 移除 .vrma 擴展名
    animation_info = {
        "id": animation_id,
        "name": file.filename[:-5],  # 顯示名稱（不含擴展名）
        "path": f"/uploads/animations/{file.filename}",
        "type": "uploaded"
    }

    # 添加到 userMotions（如果不存在）
    if not any(motion["id"] == animation_id for motion in vrm_config["userMotions"]):
        vrm_config["userMotions"].append(animation_info)
        save_config(vrm_config)
        print(f"✅ Animation added to userMotions: {animation_id}")

    return {
        "success": True,
        "animation": animation_info
    }

@app.delete("/api/animations/delete")
async def delete_animation(animation_data: dict):
    """刪除上傳的動畫檔案"""
    global vrm_config

    animation_id = animation_data.get("id")
    animation_path = animation_data.get("path")
    animation_type = animation_data.get("type")

    if not animation_id or not animation_path:
        raise HTTPException(status_code=400, detail="Animation ID and path are required")

    # 只允許刪除上傳的動畫
    if animation_type != "uploaded":
        raise HTTPException(status_code=400, detail="Cannot delete default animations")

    try:
        # 從 userMotions 移除
        vrm_config["userMotions"] = [m for m in vrm_config["userMotions"] if m["id"] != animation_id]

        # 從 selectedMotionIds 移除（如果存在）
        if animation_id in vrm_config["selectedMotionIds"]:
            vrm_config["selectedMotionIds"].remove(animation_id)

        # 刪除實際文件
        file_path = UPLOADS_DIR / "animations" / animation_path.split('/')[-1]
        if file_path.exists():
            file_path.unlink()
            print(f"🗑️ Deleted animation file: {file_path}")

        # 保存配置
        save_config(vrm_config)

        # 通知前端配置已更新
        try:
            await broadcast_to_vrm({
                "type": "config_updated",
                "data": {
                    "selectedMotionIds": vrm_config["selectedMotionIds"],
                    "timestamp": int(asyncio.get_event_loop().time() * 1000)
                }
            })
        except Exception as e:
            print(f"Warning: Failed to broadcast config update: {e}")

        return {"success": True, "message": f"動畫 {animation_id} 已刪除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刪除失敗: {str(e)}")

@app.post("/api/animations/play")
async def play_animation(animation_data: dict):
    """播放動畫"""
    animation_id = animation_data.get("id")
    if not animation_id:
        raise HTTPException(status_code=400, detail="Animation ID is required")

    try:
        await broadcast_to_vrm({
            "type": "play_animation",
            "data": {
                "animationId": animation_id,
                "animationData": animation_data
            }
        })
        return {"success": True, "message": f"動畫 {animation_id} 開始播放"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"播放動畫失敗: {str(e)}")

# ============= Animation Configuration APIs =============

# VRM 配置存儲（擴充動畫配置）
vrm_config = {
    "selectedModelId": "alice",
    "selectedModelName": "Alice.vrm",  # 新增：選中的模型名稱
    "selectedModelPath": "/vrm/Alice.vrm",  # 新增：選中的模型路徑
    "selectedMotionIds": ["akimbo", "play_fingers", "scratch_head", "stretch"],  # 預設選中所有4個動畫
    "randomPlayback": True,  # 隨機播放動畫（True=隨機, False=順序）
    "defaultModels": [
        {"id": "alice", "name": "Alice", "path": "/vrm/Alice.vrm", "type": "default"},
        {"id": "bob", "name": "Bob", "path": "/vrm/Bob.vrm", "type": "default"}
    ],
    "userModels": [],
    "defaultMotions": [
        {"id": "akimbo", "name": "插腰", "path": "/vrm/animations/akimbo.vrma", "type": "default"},
        {"id": "play_fingers", "name": "玩手指", "path": "/vrm/animations/play_fingers.vrma", "type": "default"},
        {"id": "scratch_head", "name": "撓頭", "path": "/vrm/animations/scratch_head.vrma", "type": "default"},
        {"id": "stretch", "name": "伸展", "path": "/vrm/animations/stretch.vrma", "type": "default"}
    ],
    "userMotions": []
}

# 啟動時加載配置
loaded_config = load_config()
if loaded_config:
    # 更新 vrm_config，但保留默認值作為備選
    for key in loaded_config:
        if key in vrm_config:
            vrm_config[key] = loaded_config[key]
    print(f"📋 VRM config updated from file")

# 從 vrm_config 構建 current_vrm（確保同步）
current_vrm = {
    "name": vrm_config.get("selectedModelName", "Alice.vrm"),
    "path": vrm_config.get("selectedModelPath", "/vrm/Alice.vrm")
}
print(f"🎭 Current VRM: {current_vrm['name']}")

@app.get("/api/animations/config")
async def get_animation_config():
    """獲取動畫配置"""
    return {
        "selectedMotionIds": vrm_config["selectedMotionIds"],
        "randomPlayback": vrm_config.get("randomPlayback", True),
        "defaultMotions": vrm_config["defaultMotions"],
        "userMotions": vrm_config["userMotions"]
    }

@app.post("/api/animations/config")
async def update_animation_config(config_data: dict):
    """更新動畫配置"""
    global vrm_config

    if "selectedMotionIds" in config_data:
        vrm_config["selectedMotionIds"] = config_data["selectedMotionIds"]

    if "randomPlayback" in config_data:
        vrm_config["randomPlayback"] = config_data["randomPlayback"]

    # 保存到文件（持久化）
    save_config(vrm_config)

    # 🔧 新增：通知前端配置已更新
    try:
        await broadcast_to_vrm({
            "type": "config_updated",
            "data": {
                "selectedMotionIds": vrm_config["selectedMotionIds"],
                "randomPlayback": vrm_config.get("randomPlayback", True),
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            }
        })
        print(f"✅ Animation config updated: {vrm_config['selectedMotionIds']}, random: {vrm_config.get('randomPlayback', True)}")
    except Exception as e:
        print(f"Warning: Failed to broadcast config update: {e}")

    return {"success": True, "config": vrm_config}

@app.get("/api/vrm/config")
async def get_vrm_config():
    """獲取完整的 VRM 配置（給前端使用）"""
    # 返回真實的配置，包括用戶選中的動畫
    return {"VRMConfig": vrm_config}

# ============= Reset Expression API =============

@app.post("/api/reset-expression")
async def reset_expression(stop_audio: bool = True):
    """重置所有表情，並可選擇停止音頻"""
    try:
        # 如果需要停止音頻，則觸發後端中斷機制
        if stop_audio:
            print("🛑 Reset requested: Cancelling all speech tasks")
            # 1. 設定取消標誌，中斷正在執行的 stream loop
            cancel_event.set()
            
            # 2. 清空等待中的隊列
            while not speech_queue.empty():
                try:
                    task = speech_queue.get_nowait()
                    if not task.future.done():
                        task.future.set_exception(Exception("Cancelled by user"))
                    speech_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            print("🗑️ Speech queue drained")

        await broadcast_to_vrm({
            "type": "reset_expression",
            "data": {
                "stopAudio": stop_audio
            }
        })
        return {"success": True, "message": "表情已重置" + ("，音頻已停止" if stop_audio else "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重置失敗: {str(e)}")

# ============= Health Check =============

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "connections": len(active_connections),
        "tts_engine": tts_config["engine"]
    }

# ============= Static Files =============

# 掛載靜態檔案
app.mount("/vrm", StaticFiles(directory=str(VRM_DIR)), name="vrm")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ============= Main =============

if __name__ == "__main__":
    import uvicorn
    print(f"Starting server on http://0.0.0.0:{PORT}")
    print(f"Admin panel: http://localhost:{PORT}/admin.html")
    print(f"VRM display: http://localhost:{PORT}/vrm.html")
    uvicorn.run(app, host="0.0.0.0", port=PORT)