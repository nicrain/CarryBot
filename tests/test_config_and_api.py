import http.client
import json
import os
import tempfile
import time

import pytest

import detect_stairs as ds


def test_parse_args_exists():
    args = ds.parse_args([])
    assert args is not None


def test_write_and_load_config(tmp_path):
    cfg = {"ROI_WIDTH": 111, "EDGE_THRESH": 123.0}
    p = tmp_path / "cfg.json"
    assert ds.write_config(cfg, path=str(p))
    loaded = ds.load_config(path=str(p))
    assert loaded["ROI_WIDTH"] == 111
    assert float(loaded["EDGE_THRESH"]) == 123.0


def test_http_params_get_post(tmp_path):
    # ensure no preexisting config
    cfg_file = str(tmp_path / "config.json")
    if os.path.exists(cfg_file):
        os.remove(cfg_file)

    # start server on ephemeral port
    server, t = ds.start_http_server(port=0)
    port = server.server_port

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    # GET should return current params
    conn.request("GET", "/params")
    r = conn.getresponse()
    assert r.status == 200
    data = json.loads(r.read().decode())
    assert "ROI_WIDTH" in data

    # POST update
    new = {"EDGE_THRESH": 42}
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/params", body=json.dumps(new), headers=headers)
    r = conn.getresponse()
    assert r.status == 200
    body = json.loads(r.read().decode())
    assert float(body["config"]["EDGE_THRESH"]) == 42.0

    # config file should exist if write_config worked
    # server writes to ./config.json by default
    # cleanup server
    server.shutdown()


def test_config_watcher(tmp_path):
    # create temp config file and watcher
    p = tmp_path / "cfg2.json"
    p.write_text(json.dumps({"ROI_WIDTH": 10}))
    called = {}

    def cb(cfg):
        called.update(cfg)

    watcher = ds.start_config_watcher(cb, path=str(p), interval=0.2)
    # modify file
    time.sleep(0.3)
    p.write_text(json.dumps({"ROI_WIDTH": 99}))
    # wait for watcher to pick up
    timeout = time.time() + 2
    while time.time() < timeout and not called:
        time.sleep(0.1)
    assert called.get("ROI_WIDTH") == 99
