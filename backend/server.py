import os
import json
import asyncio
from typing import List, Optional
from pathlib import Path

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

# FastAPI 應用
app = FastAPI(title="VRM Agent API")

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
        "language": "zh-CN",
        "voice": "XiaoyiNeural",
        "rate": 1.0
    },
    "indextts": {
        "server_url": "http://10.9.0.35:8001",
        "character": "hayley"
    }
}

# 當前選擇的 VRM
current_vrm = {
    "name": "Alice.vrm",
    "path": "/vrm/Alice.vrm"
}

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
    global current_vrm
    current_vrm = {
        "name": vrm_info.name,
        "path": vrm_info.path
    }
    
    # 通知 VRM 頁面切換模型
    await broadcast_to_vrm({
        "type": "switch_model",
        "data": current_vrm
    })
    
    return {"success": True, "vrm": current_vrm}

@app.post("/api/vrm/upload")
async def upload_vrm(file: UploadFile = File(...)):
    """上傳 VRM 檔案"""
    if not file.filename.endswith('.vrm'):
        raise HTTPException(status_code=400, detail="Only .vrm files are allowed")
    
    file_path = UPLOADS_DIR / file.filename
    
    # 保存檔案
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    return {
        "success": True,
        "vrm": {
            "name": file.filename,
            "path": f"/uploads/{file.filename}",
            "type": "uploaded"
        }
    }

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
                        raise HTTPException(status_code=500, detail=f"Index TTS error: {response.status}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Index TTS request failed: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported engine: {engine}")

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
    
    return {
        "success": True,
        "animation": {
            "id": f"user_{file.filename[:-5]}",  # 移除 .vrma 擴展名
            "name": file.filename,
            "path": f"/uploads/animations/{file.filename}",
            "type": "uploaded"
        }
    }

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
    "selectedMotionIds": [],  # 🎯 新增：選中的動畫 ID 列表
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

@app.get("/api/animations/config")
async def get_animation_config():
    """獲取動畫配置"""
    return {
        "selectedMotionIds": vrm_config["selectedMotionIds"],
        "defaultMotions": vrm_config["defaultMotions"],
        "userMotions": vrm_config["userMotions"]
    }

@app.post("/api/animations/config")
async def update_animation_config(config_data: dict):
    """更新動畫配置"""
    global vrm_config
    
    if "selectedMotionIds" in config_data:
        vrm_config["selectedMotionIds"] = config_data["selectedMotionIds"]
    
    # 保存到文件（可選）
    try:
        config_file = BASE_DIR / "data" / "vrm_config.json"
        config_file.parent.mkdir(exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(vrm_config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save config: {e}")
    
    # 🔧 新增：通知前端配置已更新
    try:
        await broadcast_to_vrm({
            "type": "config_updated",
            "data": {
                "selectedMotionIds": vrm_config["selectedMotionIds"],
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            }
        })
        print(f"✅ Animation config updated: {vrm_config['selectedMotionIds']}")
    except Exception as e:
        print(f"Warning: Failed to broadcast config update: {e}")
    
    return {"success": True, "config": vrm_config}

@app.get("/api/vrm/config")
async def get_vrm_config():
    """獲取完整的 VRM 配置（給前端使用）"""
    # 🔧 簡化：默認返回全部4個動畫
    simplified_config = vrm_config.copy()
    simplified_config["selectedMotionIds"] = ["akimbo", "play_fingers", "scratch_head", "stretch"]
    return {"VRMConfig": simplified_config}

# ============= Reset Expression API =============

@app.post("/api/reset-expression")
async def reset_expression():
    """重置所有表情"""
    try:
        await broadcast_to_vrm({
            "type": "reset_expression"
        })
        return {"success": True, "message": "表情已重置"}
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
