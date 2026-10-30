"""Actual hidden Windows launcher and Eel HTTP/WebSocket bridge, synthetic PDF only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from websockets.sync.client import connect
from test_redactor import ROOT, native


def test_actual_windows_launcher_and_eel_rpc():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0)); port = probe.getsockname()[1]
    output = ROOT / ".review/eel-bridge"
    output.mkdir(exist_ok=True)
    pdf = native(output / "synthetic_bridge.pdf")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    with (output / "stdout.log").open("w",encoding="utf-8") as stdout, (output / "stderr.log").open("w",encoding="utf-8") as stderr:
        child = subprocess.Popen(["cmd.exe","/d","/c",str(ROOT/"index.bat"),"--no-browser","--port",str(port)],
            cwd=ROOT,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html",timeout=1) as r:
                        assert b"eel.js" in r.read(); break
                except OSError:
                    if child.poll() is not None:
                        raise AssertionError((output/"stderr.log").read_text(encoding="utf-8"))
                    time.sleep(.1)
            else:
                raise AssertionError("Own Eel server did not become ready")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/eel.js",timeout=5) as r:
                assert b"analyze_pdf" in r.read()
            with connect(f"ws://127.0.0.1:{port}/eel?page=index.html",origin=f"http://127.0.0.1:{port}",open_timeout=5) as ws:
                def call(number,name,args):
                    ws.send(json.dumps({"call":number,"name":name,"args":args}))
                    while True:
                        reply=json.loads(ws.recv(timeout=30))
                        if reply.get("return")==number:
                            assert reply["status"]=="ok", reply
                            return reply["value"]
                status=call(1,"get_runtime_status",[])
                assert status["python_ready"] and status["ocr_ready"],status
                hits=call(2,"analyze_pdf",[str(pdf)])
                assert any(row["text"]=="Kovács Ágnes" for row in hits)
                result=call(3,"redact_pdf",[str(pdf),["Kovács Ágnes"]])
                assert result["success"] and Path(result["output_path"]).exists()
                with __import__("fitz").open(result["output_path"]) as d:
                    assert "Kovács Ágnes" not in d[0].get_text()
            (output/"result.json").write_text(json.dumps({"status":"PASS","windows_index_bat":"ACTUAL","eel_http":"ACTUAL","eel_websocket":"ACTUAL","synthetic_pdf_only":True,"port":port}),encoding="utf-8")
        finally:
            # This PID belongs to the cmd child just created above; stop its own server tree only.
            if child.poll() is None:
                subprocess.run(["taskkill","/PID",str(child.pid),"/T","/F"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
            child.wait(timeout=10)
