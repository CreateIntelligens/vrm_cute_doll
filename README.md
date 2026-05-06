# VRM 桌面寵物專案

這是一個基於 VRM 模型的桌面寵物專案，支援 TTS 語音播放、表情控制、口型同步以及 VRMA 動畫管理功能。

## 🎯 專案特色

- **VRM 模型顯示**: 支援載入和顯示 VRM 格式的 3D 角色模型（相容 VRM 0.x 與 1.0）
- **TTS 語音合成**: 整合 Edge TTS 和 Index TTS 引擎
- **序列化語音隊列**: 後端實作 Producer-Consumer 隊列，確保多個語音請求依序播放，不再混音
- **即時口型同步**: 基於音頻分析的即時對嘴動作
- **表情與動畫控制**: 
  - 支援多種 BlendShape 表情切換
  - 支援 **VRMA 動畫** 載入與輪播管理
- **中斷機制**: 可隨時停止當前語音並清空待播放隊列
- **網頁管理後台**: 
  - 視覺化管理模型與動畫
  - 支援分段語音測試與單次/循環動畫切換
- **Docker 支援**: 一鍵部署和管理

## 🚀 快速開始

### 方法 1: Docker 部署（推薦）

1. **啟動服務**
   ```bash
   cd new_agent
   docker-compose up -d
   ```

2. **訪問頁面**
   - VRM 顯示頁面: http://localhost:5456/vrm.html
   - 管理後台: http://localhost:5456/admin.html
   - 健康檢查: http://localhost:5456/health

### 方法 2: 原生運行

1. **安裝依賴**
   ```bash
   cd new_agent/backend
   pip install -r requirements.txt
   ```

2. **啟動伺服器**
   ```bash
   python server.py
   ```

3. **訪問頁面** (同上)

## 📁 專案結構

```
new_agent/
├── backend/               # 後端服務 (FastAPI + asyncio Queue)
│   ├── server.py         # 主伺服器與 TTS Worker
│   ├── requirements.txt  # Python 依賴
│   └── Dockerfile        # 容器配置
├── frontend/             # 前端頁面 (Three.js + @pixiv/three-vrm)
│   ├── vrm.html         # VRM 顯示頁面
│   └── admin.html       # 管理後台
├── vrm/                 # 預設 VRM 模型檔案
├── data/                # 配置目錄
│   ├── vrm_config.default.json  # 預設配置 (建議納入版本控制)
│   └── vrm_config.json          # 執行時配置 (已在 .gitignore 中)
└── uploads/             # 使用者上傳的模型與動畫
```

## 🎮 功能說明

### VRM 顯示頁面 (`/vrm.html`)

- **3D 角色渲染**: 使用 Three.js 進行渲染，支援透明背景。
- **語音隊列播放**: 接收後端推播的音訊分段並依序播放。
- **閒置動畫**: 當沒有語音播放時，自動隨機輪播已勾選的 VRMA 動畫。如果關閉輪播，則使用預設呼吸動畫。

### 管理後台 (`/admin.html`)

- **📦 VRM 模型管理**
  - 瀏覽與上傳 `.vrm` 模型。
  - 切換當前顯示角色。
- **🎭 動畫管理 (VRMA)**
  - **單次播放標籤頁**: 點擊動畫卡片立即讓角色執行一次特定動作（測試用）。
  - **循環播放標籤頁**: 開關自動輪播功能，並勾選哪些動畫要加入閒置時的隨機輪播清單。
  - 上傳與刪除自定義 `.vrma` 動畫檔案。
- **🔊 TTS 語音設定**
  - 設定 Edge TTS 語言、音色與語速。
  - 設定 Index TTS 伺服器與角色。
- **🎮 測試控制台**
  - 輸入長文本測試，支援前端/後端自動分段播放。
  - **中斷並清空隊列**: 一鍵停止後端生成與前端播放。

## 🔌 主要 API 接口

### 1. 語音播放 (推薦使用 stream-speak 處理長文本)
```bash
# 支援長文本自動分段與順序隊列
POST /api/stream-speak
Content-Type: application/json
{
  "text": "這是一段很長很長的氣象預報內容...",
  "expression": "happy",
  "engine": "edgetts"
}
```

### 2. 中斷語音
```bash
# 停止當前播放、中斷後端生成並清空隊列
POST /api/reset-expression?stop_audio=true
```

### 3. 配置管理
```bash
# 獲取完整配置
GET /api/vrm/config

# 更新動畫輪播設定
POST /api/animations/config
{
  "selectedMotionIds": ["akimbo", "stretch"],
  "idleLoop": true
}
```

## 🎨 VRM 模型支援

- **支援格式**: VRM 0.x 和 1.0
- **表情映射**: `happy`, `angry`, `sad`, `neutral`, `surprised`, `relaxed`
- **口型同步**: `aa` (張嘴), `ih` (閉嘴音素)

## 🔧 進階設定

### 配置持久化
本專案將預設配置與使用者設定分開：
- `data/vrm_config.default.json`: 原始預設值。
- `data/vrm_config.json`: 使用者在網頁上修改後產生的個人化設定，此檔案不會被推送到 Git。

### 自定義動畫
您可以從 VRoid Hub 或其他來源獲取 `.vrma` 檔案，透過 Admin 後台上傳後即可立即在瀏覽器中看到效果。

## 📺 YouTube 直播聊天室整合 (選填)

本專案支援在 Agent 說話時，自動將文字同步發送到您正在直播的 YouTube 聊天室。

### ⚠️ 安全警告
**請勿將以下敏感檔案上傳至 GitHub 或公開空間：**
- `data/client_secret.json`
- `data/token.pickle`
- `data/youtube_token.json`

這些檔案包含您的 Google 帳號存取權限。專案已在 `.gitignore` 中設定忽略這些檔案。

### 設定教學
1. **獲取 OAuth 憑證**：
   - 前往 [Google Cloud Console](https://console.cloud.google.com/)。
   - 啟用 **YouTube Data API v3**。
   - 建立 **OAuth 2.0 Client ID** (類型選 `Desktop App`)。
   - 下載 JSON 檔案，重新命名為 `client_secret.json` 並放入 `data/` 目錄。

2. **生成授權 Token**：
   - 若您已有 `token.pickle`，請直接放入 `data/` 目錄。
   - 若無，請在有瀏覽器的電腦執行 `backend/setup_youtube.py` 來進行登入授權，生成 `youtube_token.json` 後放入伺服器的 `data/`。

3. **運作方式**：
   - 只要 `data/` 目錄下存在有效的憑證，且您的帳號正在進行 **活躍直播 (Active Live Stream)**，系統就會在您呼叫 `/api/speak` 或 `/api/stream-speak` 時自動發送訊息。

---

**享受你的 VRM 桌面寵物體驗！** 🎉