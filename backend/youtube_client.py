import os
import json
import pickle
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# 設定路徑
BASE_DIR = Path("/app")
DATA_DIR = BASE_DIR / "data"
TOKEN_FILE_JSON = DATA_DIR / "youtube_token.json"
TOKEN_FILE_PICKLE = DATA_DIR / "token.pickle"
CLIENT_SECRETS_FILES = [DATA_DIR / "client_secret.json", DATA_DIR / "client_secrets.json"]

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

def get_authenticated_service():
    """獲取驗證過的 YouTube Service"""
    creds = None
    
    # 1. 優先嘗試讀取 JSON Token
    if TOKEN_FILE_JSON.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE_JSON), SCOPES)
        except Exception as e:
            print(f"⚠️ YouTube JSON token error: {e}")

    # 2. 如果沒有 JSON，嘗試讀取 Pickle Token (您現有的檔案)
    if not creds and TOKEN_FILE_PICKLE.exists():
        try:
            with open(TOKEN_FILE_PICKLE, 'rb') as token:
                creds = pickle.load(token)
            print("✅ Loaded credentials from token.pickle")
            
            # 順便存一份 JSON 備份
            with open(TOKEN_FILE_JSON, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"⚠️ YouTube pickle token error: {e}")

    # 如果沒有憑證或憑證無效
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # 保存刷新後的 token
                with open(TOKEN_FILE_JSON, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                print(f"⚠️ Failed to refresh YouTube token: {e}")
                return None
        else:
            return None

    try:
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ Failed to build YouTube service: {e}")
        return None

def get_active_live_chat_id(youtube):
    """獲取當前活躍直播的 Chat ID"""
    try:
        # 查詢當前正在直播的廣播
        request = youtube.liveBroadcasts().list(
            part="snippet",
            broadcastStatus="active",
            broadcastType="all"
        )
        response = request.execute()
        
        items = response.get("items", [])
        if not items:
            return None
            
        # 返回第一個活躍直播的 chat ID
        return items[0]["snippet"]["liveChatId"]
        
    except Exception as e:
        print(f"⚠️ Error finding live broadcast: {e}")
        return None

def send_chat_message(text, override_chat_id=None):
    """發送訊息到 YouTube 直播聊天室"""
    if not TOKEN_FILE_JSON.exists() and not TOKEN_FILE_PICKLE.exists():
        print("ℹ️ Skipping YouTube: No token files found in data/ directory.")
        return

    try:
        youtube = get_authenticated_service()
        if not youtube:
            print("ℹ️ Skipping YouTube: Failed to authenticate or build service.")
            return

        # 優先用指定的 chat_id，否則自動找第一個活躍直播
        live_chat_id = override_chat_id or get_active_live_chat_id(youtube)
        if not live_chat_id:
            print("ℹ️ Skipping YouTube: No active live stream found for this account.")
            return

        # 2. 限制字數 (YouTube 聊天室上限為 200 字)
        safe_text = text
        if len(safe_text) > 200:
            safe_text = safe_text[:197] + "..."
            print(f"✂️ Message truncated for YouTube (original length: {len(text)})")

        # 3. 發送訊息
        request = youtube.liveChatMessages().insert(
            part="snippet",
            body={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {
                        "messageText": safe_text
                    }
                }
            }
        )
        response = request.execute()
        print(f"✅ YouTube Success: Sent message to chat ({safe_text[:30]}...)")
        
    except Exception as e:
        print(f"❌ YouTube Error: Failed to send message: {e}")
