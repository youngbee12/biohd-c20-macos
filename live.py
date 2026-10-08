#!/usr/bin/env python3
import ctypes
import io
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image

import toupcam


PORT = int(os.environ.get("BIOHD_PORT", "8765"))
latest_jpeg = b""
latest_lock = threading.Lock()
frame_event = threading.Event()
white_balance_event = threading.Event()
first_frame = threading.Event()
stop_event = threading.Event()
camera_error = None
camera = None
limits = {}


def on_camera_event(event, _):
    global camera_error
    if event == toupcam.TOUPCAM_EVENT_IMAGE:
        frame_event.set()
    elif event in (toupcam.TOUPCAM_EVENT_TEMPTINT, toupcam.TOUPCAM_EVENT_WBGAIN):
        white_balance_event.set()
    elif event in (
        toupcam.TOUPCAM_EVENT_ERROR,
        toupcam.TOUPCAM_EVENT_DISCONNECTED,
        toupcam.TOUPCAM_EVENT_NOFRAMETIMEOUT,
        toupcam.TOUPCAM_EVENT_NOPACKETTIMEOUT,
    ):
        camera_error = f"相机事件错误：0x{event:x}"
        frame_event.set()


def capture_frames(width, height):
    global latest_jpeg, camera_error
    buffer = ctypes.create_string_buffer(width * height * 3)
    info = toupcam.ToupcamFrameInfoV4()
    try:
        camera.StartPullModeWithCallback(on_camera_event, None)
        while not stop_event.is_set():
            if not frame_event.wait(1):
                continue
            frame_event.clear()
            if camera_error:
                break
            camera.PullImageV4(buffer, 0, 24, -1, info)
            if not info.v3.width:
                continue
            image = Image.frombuffer("RGB", (width, height), buffer.raw, "raw", "RGB", 0, 1)
            encoded = io.BytesIO()
            image.save(encoded, "JPEG", quality=82)
            with latest_lock:
                latest_jpeg = encoded.getvalue()
            first_frame.set()
    except Exception as error:
        camera_error = str(error)
        first_frame.set()


def page():
    exposure = camera.get_ExpoTime() / 1000
    gain = camera.get_ExpoAGain()
    temperature, tint = camera.get_TempTint()
    emin, emax, _ = limits["exposure"]
    gmin, gmax, _ = limits["gain"]
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BioHD-C20 实时预览</title>
<style>
body{{margin:0;background:#111;color:#eee;font:15px -apple-system,BlinkMacSystemFont,sans-serif}}
header{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:10px 18px;background:#1c1c1e;position:sticky;top:0}}
h1{{font-size:17px;margin:0 auto 0 0}} label{{white-space:nowrap}} input[type=number]{{width:90px}}
button,a{{background:#3a7afe;color:white;border:0;border-radius:7px;padding:7px 11px;text-decoration:none}}
main{{height:calc(100vh - 58px);display:grid;place-items:center}} img{{max-width:100%;max-height:100%;object-fit:contain}}
</style>
<header><h1>BioHD-C20 · 1824×1216</h1>
<label><input id="auto" type="checkbox" checked> 自动曝光</label>
<label>曝光 ms <input id="exposure" type="number" min="{emin/1000}" max="{emax/1000}" step="0.1" value="{exposure:.1f}"></label>
<label>增益 % <input id="gain" type="number" min="{gmin}" max="{gmax}" value="{gain}"></label>
<label>色温 K <input id="temperature" type="number" min="2000" max="15000" value="{temperature}"></label>
<label>色调 <input id="tint" type="number" min="200" max="2500" value="{tint}"></label>
<button onclick="apply()">应用</button><button onclick="awb()">一键白平衡</button>
<button onclick="resetWB()">白平衡默认值</button><a href="/snapshot.jpg">保存当前帧</a></header>
<main><img id="preview" alt="BioHD-C20 实时画面"></main>
<script>
const img=document.querySelector('#preview');
setInterval(()=>img.src='/frame.jpg?t='+Date.now(),120);
async function control(query){{const data=await (await fetch('/control?'+query)).json();temperature.value=data.temperature;tint.value=data.tint}}
function apply(){{control(`auto=${{auto.checked?1:0}}&exposure=${{exposure.value}}&gain=${{gain.value}}&temperature=${{temperature.value}}&tint=${{tint.value}}`)}}
function awb(){{control('awb=1')}} function resetWB(){{control('resetwb=1')}}
</script></html>""".encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/":
            self.reply(page(), "text/html; charset=utf-8")
        elif route.path in ("/frame.jpg", "/snapshot.jpg"):
            with latest_lock:
                data = latest_jpeg
            headers = {"Cache-Control": "no-store"}
            if route.path == "/snapshot.jpg":
                headers["Content-Disposition"] = 'attachment; filename="biohd-c20.jpg"'
            self.reply(data, "image/jpeg", headers)
        elif route.path == "/control":
            query = parse_qs(route.query)
            if "awb" in query:
                white_balance_event.clear()
                camera.AwbOnce()
                white_balance_event.wait(3)
            elif "resetwb" in query:
                camera.put_TempTint(toupcam.TOUPCAM_TEMP_DEF, toupcam.TOUPCAM_TINT_DEF)
            elif "temperature" in query:
                camera.put_TempTint(int(query["temperature"][0]), int(query["tint"][0]))
            if "auto" in query:
                auto = int(query["auto"][0])
                camera.put_AutoExpoEnable(auto)
            if "auto" in query and not auto:
                emin, emax, _ = limits["exposure"]
                gmin, gmax, _ = limits["gain"]
                exposure = int(float(query["exposure"][0]) * 1000)
                gain = int(query["gain"][0])
                camera.put_ExpoTime(max(emin, min(emax, exposure)))
                camera.put_ExpoAGain(max(gmin, min(gmax, gain)))
            temperature, tint = camera.get_TempTint()
            self.reply(json.dumps({"ok": True, "temperature": temperature, "tint": tint}).encode(), "application/json")
        else:
            self.send_error(404)

    def reply(self, data, content_type, headers=None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


def main():
    global camera, limits
    devices = toupcam.Toupcam.EnumV2()
    if not devices:
        raise SystemExit("未找到 BioHD-C20，请检查 USB 连接。")
    camera = toupcam.Toupcam.Open(devices[0].id)
    if not camera:
        raise SystemExit("BioHD-C20 打开失败。")
    try:
        camera.put_eSize(2)
        camera.put_AutoExpoEnable(1)
        limits = {"exposure": camera.get_ExpTimeRange(), "gain": camera.get_ExpoAGainRange()}
        width, height = camera.get_Size()
        worker = threading.Thread(target=capture_frames, args=(width, height), daemon=True)
        worker.start()
        if not first_frame.wait(8):
            raise SystemExit("相机已打开，但 8 秒内没有收到画面。")
        if camera_error:
            raise SystemExit(camera_error)
        if "--check" in sys.argv:
            with latest_lock:
                path = os.path.join(os.path.dirname(__file__), "last-frame.jpg")
                with open(path, "wb") as output:
                    output.write(latest_jpeg)
            print(path)
            return
        url = f"http://127.0.0.1:{PORT}"
        print(f"BioHD-C20 实时预览：{url}（关闭终端即可停止）")
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        try:
            ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        stop_event.set()
        camera.Close()


if __name__ == "__main__":
    main()
