# vtuber studio 表情websocket
import json
from threading import Thread
from flask import Flask, jsonify, request
import websocket

app = Flask(__name__)

def run_forever():
    ws.run_forever(ping_timeout=1)

def on_open(ws):
    auth()   

ws = websocket.WebSocketApp("ws://127.0.0.1:8001",on_open = on_open)


def auth():
    #授权码
    auth={
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": "SomeID",
        "messageType": "AuthenticationRequest",
        "data": {
            "pluginName": "Cheers Bot",
            "pluginDeveloper": "winlone",
            "authenticationToken": "7dc9bb48d9efdfc88c6f49e1a2fdd51fa3a396681fb882b59e373428cea32413"
        }
    }
    data=json.dumps(auth)
    ws.send(data)


@app.route("/emote", methods=["POST"])
def emote_ws_thread():
    data = request.json
    text=data["text"]
    emote_thread1 = Thread(target=emote_ws,args=(text,))
    emote_thread1.start()
    return "ok"

def emote_ws(text):
    #发送表情
    jstr={
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": "SomeID11",
        "messageType": "HotkeyTriggerRequest",
        "data": {
            "hotkeyID": text
        }
    }
    data=json.dumps(jstr)
    ws.send(data)



if __name__ == "__main__":
    init_thread = Thread(target=run_forever)
    init_thread.start()
    # 开始监听弹幕流
    app.run(host="0.0.0.0", port=1800)
    


