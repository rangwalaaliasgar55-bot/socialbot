# Package SocialBot as a desktop app

## Option A — Tauri (recommended, small binary)
1. Install Rust + Tauri CLI
2. Create app with webview at `http://127.0.0.1:8000`
3. Sidecar: run `socialbot dashboard` as child process on launch
4. ChatGPT login still via system browser (OAuth localhost callback)

## Option B — Electron
1. electron-builder main process starts `socialbot dashboard`
2. BrowserWindow loads localhost dashboard
3. Same OAuth flow

## Option C — pure web (already works)
```bash
socialbot dashboard
# bookmark http://localhost:8000
```

AI = ChatGPT account OAuth (`socialbot chatgpt login`) or your own API key. No piracy layer.
