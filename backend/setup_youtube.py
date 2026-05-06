import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# 這需要在有瀏覽器的環境執行
# 執行後會生成 data/youtube_token.json

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
CLIENT_SECRETS_FILE = "client_secrets.json" # 您需要從 Google Cloud Console 下載這個檔案
TOKEN_FILE = "data/youtube_token.json"

def main():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"❌ 請先將 {CLIENT_SECRETS_FILE} 放在此目錄下。")
        print("您可以從 Google Cloud Console > APIs & Services > Credentials 下載。")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    # 確保 data 目錄存在
    os.makedirs("data", exist_ok=True)

    # 保存 Token
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    
    print(f"✅ 認證成功！Token 已保存至 {TOKEN_FILE}")
    print("請將此檔案複製到伺服器的 data/ 目錄中。")

if __name__ == "__main__":
    main()
