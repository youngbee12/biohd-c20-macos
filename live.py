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
ffc_event = threading.Event()
dfc_event = threading.Event()
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
    elif event == toupcam.TOUPCAM_EVENT_FFC:
        ffc_event.set()
    elif event == toupcam.TOUPCAM_EVENT_DFC:
        dfc_event.set()
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


def camera_state():
    temperature, tint = camera.get_TempTint()
    return {
        "auto": camera.get_AutoExpoEnable(),
        "exposure": camera.get_ExpoTime() / 1000,
        "gain": camera.get_ExpoAGain(),
        "exposure_target": camera.get_AutoExpoTarget(),
        "temperature": temperature,
        "tint": tint,
        "hue": camera.get_Hue(),
        "saturation": camera.get_Saturation(),
        "brightness": camera.get_Brightness(),
        "contrast": camera.get_Contrast(),
        "gamma": camera.get_Gamma(),
        "ffc": camera.get_Option(toupcam.TOUPCAM_OPTION_FFC) & 0xff,
        "dfc": camera.get_Option(toupcam.TOUPCAM_OPTION_DFC) & 0xff,
    }


def bounded(query, name, minimum, maximum):
    return max(minimum, min(maximum, int(float(query[name][0]))))


def page():
    state = camera_state()
    auto_checked = "checked" if state["auto"] else ""
    emin, emax, _ = limits["exposure"]
    gmin, gmax, _ = limits["gain"]
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BioHD-C20 实时预览</title>
<style>
body{{margin:0;background:#111;color:#eee;font:15px -apple-system,BlinkMacSystemFont,sans-serif}}
header,.advanced{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:10px 18px;background:#1c1c1e}}
header{{position:sticky;top:0;z-index:2}} details{{background:#252527}} summary{{cursor:pointer;padding:9px 18px}}
h1{{font-size:17px;margin:0 auto 0 0}} label{{white-space:nowrap}} input[type=number]{{width:90px}}
button,a{{background:#3a7afe;color:white;border:0;border-radius:7px;padding:7px 11px;text-decoration:none}}
button.secondary{{background:#555}} main{{height:calc(100vh - 58px);display:grid;place-items:center}} img{{max-width:100%;max-height:100%;object-fit:contain}}
</style>
<header><h1>BioHD-C20 · 1824×1216</h1>
<label><input id="auto" type="checkbox" {auto_checked}> 自动曝光</label>
<label>曝光 ms <input id="exposure" type="number" min="{emin/1000}" max="{emax/1000}" step="0.1" value="{state['exposure']:.1f}"></label>
<label>增益 % <input id="gain" type="number" min="{gmin}" max="{gmax}" value="{state['gain']}"></label>
<label>色温 K <input id="temperature" type="number" min="2000" max="15000" value="{state['temperature']}"></label>
<label>Tint <input id="tint" type="number" min="200" max="2500" value="{state['tint']}"></label>
<button onclick="apply()">应用</button><button onclick="awb()">一键白平衡</button>
<button onclick="resetWB()">白平衡默认值</button><a href="/snapshot.jpg">保存当前帧</a></header>
<details><summary>FLUOCA 风格高级色彩控制</summary><div class="advanced">
<label>曝光目标 <input id="exposure_target" type="number" min="16" max="220" value="{state['exposure_target']}"></label>
<label>色相 <input id="hue" type="number" min="-180" max="180" value="{state['hue']}"></label>
<label>饱和度 <input id="saturation" type="number" min="0" max="255" value="{state['saturation']}"></label>
<label>亮度 <input id="brightness" type="number" min="-255" max="255" value="{state['brightness']}"></label>
<label>对比度 <input id="contrast" type="number" min="-255" max="255" value="{state['contrast']}"></label>
<label>Gamma <input id="gamma" type="number" min="20" max="180" value="{state['gamma']}"></label>
<button onclick="applyColor()">应用色彩</button><button class="secondary" onclick="resetColor()">恢复中性默认值</button>
<button class="secondary" onclick="flatField()">采集并启用平场校正</button>
<button class="secondary" onclick="darkField()">采集并启用暗场校正</button>
</div></details>
<main><img id="preview" alt="BioHD-C20 实时画面"></main>
<script>
const img=document.querySelector('#preview');
setInterval(()=>img.src='/frame.jpg?t='+Date.now(),120);
async function control(query){{const data=await (await fetch('/control?'+query)).json();for(const [key,value] of Object.entries(data)){{const el=document.getElementById(key);if(!el||key==='ok')continue;if(key==='auto')el.checked=Boolean(value);else el.value=value}}}}
function apply(){{control(`auto=${{auto.checked?1:0}}&exposure=${{exposure.value}}&gain=${{gain.value}}&temperature=${{temperature.value}}&tint=${{tint.value}}`)}}
function awb(){{control('awb=1')}} function resetWB(){{control('resetwb=1')}}
function applyColor(){{control(`color=1&exposure_target=${{exposure_target.value}}&hue=${{hue.value}}&saturation=${{saturation.value}}&brightness=${{brightness.value}}&contrast=${{contrast.value}}&gamma=${{gamma.value}}`)}}
function resetColor(){{control('resetcolor=1')}}
function flatField(){{if(confirm('移开样品，保持当前照明和焦点，再采集平场。是否继续？'))control('ffc=1')}}
function darkField(){{if(confirm('完全盖住镜头，并保持当前曝光和增益，再采集暗场。是否继续？'))control('dfc=1')}}
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
                camera.put_TempTint(
                    bounded(query, "temperature", toupcam.TOUPCAM_TEMP_MIN, toupcam.TOUPCAM_TEMP_MAX),
                    bounded(query, "tint", toupcam.TOUPCAM_TINT_MIN, toupcam.TOUPCAM_TINT_MAX),
                )
            if "resetcolor" in query:
                camera.put_AutoExpoTarget(toupcam.TOUPCAM_AETARGET_DEF)
                camera.put_Hue(toupcam.TOUPCAM_HUE_DEF)
                camera.put_Saturation(toupcam.TOUPCAM_SATURATION_DEF)
                camera.put_Brightness(toupcam.TOUPCAM_BRIGHTNESS_DEF)
                camera.put_Contrast(toupcam.TOUPCAM_CONTRAST_DEF)
                camera.put_Gamma(toupcam.TOUPCAM_GAMMA_DEF)
            elif "color" in query:
                camera.put_AutoExpoTarget(bounded(query, "exposure_target", toupcam.TOUPCAM_AETARGET_MIN, toupcam.TOUPCAM_AETARGET_MAX))
                camera.put_Hue(bounded(query, "hue", toupcam.TOUPCAM_HUE_MIN, toupcam.TOUPCAM_HUE_MAX))
                camera.put_Saturation(bounded(query, "saturation", toupcam.TOUPCAM_SATURATION_MIN, toupcam.TOUPCAM_SATURATION_MAX))
                camera.put_Brightness(bounded(query, "brightness", toupcam.TOUPCAM_BRIGHTNESS_MIN, toupcam.TOUPCAM_BRIGHTNESS_MAX))
                camera.put_Contrast(bounded(query, "contrast", toupcam.TOUPCAM_CONTRAST_MIN, toupcam.TOUPCAM_CONTRAST_MAX))
                camera.put_Gamma(bounded(query, "gamma", toupcam.TOUPCAM_GAMMA_MIN, toupcam.TOUPCAM_GAMMA_MAX))
            if "ffc" in query:
                ffc_event.clear()
                camera.put_Option(toupcam.TOUPCAM_OPTION_FFC, 0xff000010)
                camera.FfcOnce()
                ffc_event.wait(5)
                camera.put_Option(toupcam.TOUPCAM_OPTION_FFC, 1)
            if "dfc" in query:
                dfc_event.clear()
                camera.put_Option(toupcam.TOUPCAM_OPTION_DFC, 0xff000010)
                camera.DfcOnce()
                dfc_event.wait(5)
                camera.put_Option(toupcam.TOUPCAM_OPTION_DFC, 1)
            if "auto" in query:
                auto = bounded(query, "auto", 0, 1)
                try:
                    camera.put_AutoExpoEnable(auto)
                except toupcam.HRESULTException:
                    pass
            if "auto" in query and not auto:
                emin, emax, _ = limits["exposure"]
                gmin, gmax, _ = limits["gain"]
                exposure = int(float(query["exposure"][0]) * 1000)
                gain = int(query["gain"][0])
                camera.put_ExpoTime(max(emin, min(emax, exposure)))
                camera.put_ExpoAGain(max(gmin, min(gmax, gain)))
            self.reply(json.dumps({"ok": True, **camera_state()}).encode(), "application/json")
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
        try:
            camera.put_AutoExpoEnable(1)
        except toupcam.HRESULTException:
            pass
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
