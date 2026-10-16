import json
import time
import base64
import requests
import websocket

DEBUG_URL = "http://127.0.0.1:9222"

# 1. 获取所有调试目标，找到第一个页面
targets = requests.get(f"{DEBUG_URL}/json").json()
page = next(t for t in targets if t["type"] == "page")
ws_url = page["webSocketDebuggerUrl"]
print("WebSocket 地址:", ws_url)

# 2. 连接页面级 WebSocket
ws = websocket.create_connection(ws_url)
msg_id = 0

def cdp(method, params=None):
    """发送一条 CDP 命令并等待对应响应"""
    global msg_id
    msg_id += 1
    payload = {
        "id": msg_id,
        "method": method,
        "params": params or {}
    }
    ws.send(json.dumps(payload))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            if "error" in msg:
                raise Exception(msg["error"])
            return msg.get("result", {})

# 3. 导航到目标网页
cdp("Page.enable")
cdp("Page.navigate", {"url": "https://baidu.com"})
time.sleep(2)  # 简单等待加载；生产环境应监听 Page.loadEventFired 事件

# 4. 执行 JavaScript 获取标题
result = cdp("Runtime.evaluate", {
    "expression": "document.title",
    "returnByValue": True
})
print("页面标题:", result["result"]["value"])

# 5. 截图并保存
shot = cdp("Page.captureScreenshot", {"format": "png"})
with open("cdp_screenshot.png", "wb") as f:
    f.write(base64.b64decode(shot["data"]))
print("截图已保存: cdp_screenshot.png")

ws.close()