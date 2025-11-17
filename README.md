# VRM 桌面寵物專案

這是一個基於 VRM 模型的桌面寵物專案，支援 TTS 語音播放、表情控制和口型同步功能。

## 🎯 專案特色

- **VRM 模型顯示**: 支援載入和顯示 VRM 格式的 3D 角色模型
- **TTS 語音合成**: 整合 Edge TTS 和 Index TTS 引擎
- **口型同步**: 基於音頻分析的即時口型同步
- **表情控制**: 支援多種表情切換（開心、生氣、悲傷等）
- **即時通信**: 使用 WebSocket 進行前後端即時通訊
- **網頁管理後台**: 友善的 Web 界面進行設定和測試
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
├── backend/               # 後端服務
│   ├── server.py         # 主伺服器
│   ├── requirements.txt  # Python 依賴
│   └── Dockerfile        # 容器配置
├── frontend/             # 前端頁面
│   ├── vrm.html         # VRM 顯示頁面
│   └── admin.html       # 管理後台
├── vrm/                 # VRM 模型檔案
│   ├── Alice.vrm        # 預設女性角色
│   ├── Bob.vrm          # 預設男性角色
│   └── animations/      # 動畫檔案
└── docker-compose.yml   # Docker 編排
```

## 🎮 功能說明

### VRM 顯示頁面 (`/vrm.html`)

- **3D 角色顯示**: 使用 Three.js 和 @pixiv/three-vrm 渲染 VRM 模型
- **即時語音播放**: 接收 TTS 音訊並播放
- **口型同步**: 根據音頻強度動態調整角色嘴部動作
- **表情變化**: 支援 happy、angry、sad、neutral、surprised、relaxed 等表情
- **字幕顯示**: 可拖曳的字幕顯示框
- **相機控制**: 支援滑鼠拖曳和縮放視角

### 管理後台 (`/admin.html`)

- **VRM 模型管理**
  - 瀏覽可用的 VRM 模型
  - 上傳新的 VRM 檔案
  - 切換當前使用的模型

- **TTS 語音設定**
  - Edge TTS 設定（語言、音色、語速）
  - Index TTS 設定（伺服器地址、角色）
  - 即時儲存和套用設定

- **測試控制台**
  - 輸入測試文字
  - 選擇表情效果
  - 立即播放測試
  - API 使用說明

## 🔌 API 接口

### 1. 語音播放
```bash
POST /api/speak
Content-Type: application/json

{
  "text": "你好，我是虛擬助手",
  "expression": "happy",
  "engine": "edgetts"
}
```

### 2. VRM 模型管理
```bash
# 獲取模型列表
GET /api/vrm/list

# 切換模型
POST /api/vrm/select
Content-Type: application/json
{
  "name": "Alice",
  "path": "/vrm/Alice.vrm",
  "type": "default"
}

# 上傳模型
POST /api/vrm/upload
Content-Type: multipart/form-data
file: [VRM 檔案]
```

### 3. TTS 設定
```bash
# 獲取設定
GET /api/tts/config

# 更新設定
POST /api/tts/config
Content-Type: application/json
{
  "engine": "edgetts",
  "edgetts": {
    "language": "zh-TW",
    "voice": "XiaoyiNeural",
    "rate": 1.0
  }
}
```

## 🛠️ 技術棧

### 後端
- **FastAPI**: 高性能 Web 框架
- **WebSocket**: 即時通訊
- **edge-tts**: 微軟 Edge TTS 引擎
- **httpx**: 異步 HTTP 客戶端

### 前端
- **Three.js**: 3D 圖形渲染
- **@pixiv/three-vrm**: VRM 模型支援
- **Web Audio API**: 音訊分析和播放
- **WebSocket**: 即時通訊

### 部署
- **Docker**: 容器化部署
- **Docker Compose**: 服務編排

## 🎨 VRM 模型支援

### 支援格式
- VRM 0.x 和 1.0 格式
- 標準 VRM 表情（BlendShapes）
- Spring Bone 物理模擬

### 表情映射
- `happy` → 開心表情
- `angry` → 生氣表情  
- `sad` → 悲傷表情
- `neutral` → 中性表情
- `surprised` → 驚訝表情
- `relaxed` → 放鬆表情

### 口型同步
- `aa` → 張嘴音素
- `ih` → 閉嘴音素
- 基於音頻頻譜分析的即時驅動

## 📝 使用範例

### Python 整合
```python
import requests

# 讓角色說話
response = requests.post('http://localhost:5456/api/speak', json={
    'text': '歡迎來到我的世界！',
    'expression': 'happy'
})

# 切換角色
requests.post('http://localhost:5456/api/vrm/select', json={
    'name': 'Bob',
    'path': '/vrm/Bob.vrm',
    'type': 'default'
})
```

### JavaScript 整合
```javascript
// 讓角色說話
fetch('/api/speak', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: '你好，世界！',
    expression: 'surprised'
  })
});

// 監聽 WebSocket
const ws = new WebSocket('ws://localhost:5456/ws/vrm');
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('收到訊息:', message);
};
```

## 🔧 進階設定

### Index TTS 設定
如果使用 Index TTS，需要：
1. 部署 Index TTS 伺服器
2. 在管理後台設定伺服器地址和角色名稱
3. 確保網路連通性

### 自定義 VRM 模型
1. 準備符合規範的 VRM 檔案
2. 透過管理後台上傳
3. 確認表情和骨骼設定正確

### 效能優化
- VRM 模型建議大小 < 50MB
- 音訊位元率建議 44.1kHz
- 瀏覽器建議使用 Chrome 或 Firefox

## 🐛 常見問題

### Q: VRM 模型載入失敗
- 檢查模型檔案格式是否正確
- 確認模型大小不要過大
- 查看瀏覽器開發者工具的錯誤訊息

### Q: 沒有聲音播放
- 檢查瀏覽器音訊權限
- 確認 TTS 服務設定正確
- 查看 WebSocket 連線狀態

### Q: 口型同步不準確
- 調整音訊增益設定
- 檢查瀏覽器對 Web Audio API 支援
- 確認 VRM 模型包含正確的 BlendShapes

## 📄 授權條款

本專案基於原 super-agent-party 專案改進，遵循相同的開源協議。

## 🤝 貢獻指南

歡迎提交 Issue 和 Pull Request 來改進本專案！

---

**享受你的 VRM 桌面寵物體驗！** 🎉
