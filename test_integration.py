#!/usr/bin/env python3
"""
pi-list integration test suite.
Tests the full upload → analyse → inspect → MP3 render pipeline
against the running pi-list instance using sample pcaps from the repo.
"""

import sys
import time
import json
import os
import subprocess
import urllib.request
import urllib.error

BASE_URL = "http://10.0.0.3:8080"
USERNAME = "test-ci"
PASSWORD = "testci123"
SAMPLE_DIR = "/home/rhys/src/pi-list/sample_data/pcap"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

results = []


def check(name, passed, detail=""):
    status = PASS if passed else FAIL
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    results.append((name, passed))


def request(method, path, token=None, data=None, as_json=True):
    url = BASE_URL + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, json.loads(raw) if as_json else raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {}


def upload_pcap(token, pcap_path):
    """Upload a pcap file using multipart/form-data via curl (no requests lib)."""
    result = subprocess.run(
        ["curl", "-s", "-X", "PUT",
         "-H", f"Authorization: Bearer {token}",
         "-F", f"pcap=@{pcap_path}",
         f"{BASE_URL}/api/pcap"],
        capture_output=True, text=True, timeout=30
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def wait_for_analysis(token, pcap_id, timeout=30):
    for _ in range(timeout // 3):
        _, data = request("GET", f"/api/pcap/{pcap_id}", token)
        if isinstance(data, dict) and data.get("analyzed"):
            return data
        time.sleep(3)
    return None


def get_token():
    _, data = request("POST", "/auth/login", data={"username": USERNAME, "password": PASSWORD})
    return data.get("content", {}).get("token")


# ── Test cases ────────────────────────────────────────────────────────────────

def test_health():
    print("\n── Health check ──")
    code, _ = request("GET", "/api/meta/version", as_json=False)
    check("Web UI responds with HTTP 200", code == 200, f"HTTP {code}")


def test_auth(token):
    print("\n── Authentication ──")
    check("Login returns JWT token", bool(token), token[:20] + "..." if token else "no token")

    _, data = request("GET", "/api/pcap", token)
    check("Authenticated request accepted", isinstance(data, list), type(data).__name__)

    code, _ = request("GET", "/api/pcap")
    check("Unauthenticated request rejected (401/403)", code in (401, 403), f"HTTP {code}")


def test_pcap(token, label, pcap_path, expected):
    """
    Generic pcap test.
    expected: dict with keys like audio_streams, video_streams, anc_streams, etc.
    Returns pcap_id for further tests.
    """
    print(f"\n── {label} ──")
    name = os.path.basename(pcap_path)

    upload = upload_pcap(token, pcap_path)
    pcap_id = upload.get("uuid")
    check(f"Upload {name}", bool(pcap_id), pcap_id or "no uuid returned")
    if not pcap_id:
        return None

    result = wait_for_analysis(token, pcap_id)
    check("Analysis completes", result is not None, "timed out" if result is None else "ok")
    if not result:
        return pcap_id

    for key, val in expected.items():
        actual = result.get(key)
        check(f"  {key} == {val}", actual == val, f"got {actual}")

    _, streams = request("GET", f"/api/pcap/{pcap_id}/streams", token)
    check("Streams endpoint returns list", isinstance(streams, list), f"{len(streams)} streams" if isinstance(streams, list) else type(streams).__name__)

    # JSON report (requires ?type=json)
    code, _ = request("GET", f"/api/pcap/{pcap_id}/report?type=json", token)
    check("JSON report available", code == 200, f"HTTP {code}")

    return pcap_id


def test_mp3(token, pcap_id, channels=None):
    print("\n── MP3 audio render (ffmpeg fix) ──")
    _, streams = request("GET", f"/api/pcap/{pcap_id}/streams", token)
    audio = [s for s in (streams if isinstance(streams, list) else []) if s.get("media_type") == "audio"]
    if not audio:
        print(f"  [{SKIP}] No audio streams in pcap")
        return

    stream_id = audio[0]["id"]
    n_ch = audio[0].get("media_specific", {}).get("number_channels", 1)
    test_channels = channels or list(range(min(n_ch, 4)))

    for ch in test_channels:
        # Trigger render
        request("GET", f"/api/pcap/{pcap_id}/stream/{stream_id}/rendermp3?channels={ch}", token)

    time.sleep(max(5, len(test_channels) * 2))

    for ch in test_channels:
        result = subprocess.run(
            ["curl", "-s", "-o", f"/tmp/opencode/mp3_ch{ch}.mp3",
             "-w", "%{http_code}",
             "-H", f"Authorization: Bearer {token}",
             f"{BASE_URL}/api/pcap/{pcap_id}/stream/{stream_id}/downloadmp3?channels={ch}"],
            capture_output=True, text=True, timeout=15
        )
        code = result.stdout.strip()
        size = os.path.getsize(f"/tmp/opencode/mp3_ch{ch}.mp3") if os.path.exists(f"/tmp/opencode/mp3_ch{ch}.mp3") else 0
        is_mp3 = size > 1000  # valid MP3 will be at least a few KB
        check(f"Channel {ch}: HTTP {code}, size {size}B", code == "200" and is_mp3,
              "valid MP3" if is_mp3 else "empty or error")


def test_summary():
    print("\n" + "═" * 50)
    passed = sum(1 for _, p in results if p)
    total = len(results)
    failed = total - passed
    status = PASS if failed == 0 else FAIL
    print(f"[{status}] {passed}/{total} tests passed" + (f", {failed} failed" if failed else ""))
    if failed:
        print("\nFailed tests:")
        for name, p in results:
            if not p:
                print(f"  ✗ {name}")
    return failed == 0


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("pi-list integration tests")
    print(f"Target: {BASE_URL}")
    print("=" * 50)

    test_health()

    token = get_token()
    test_auth(token)

    # ST 2110-30 audio (8-channel L24) — also exercises the MP3 fix
    audio_pcap_id = test_pcap(token, "ST 2110-30 Audio (L24 8ch)",
        f"{SAMPLE_DIR}/st2110/2110-30/l24_48000_8ch_0125.pcap",
        {"audio_streams": 1, "video_streams": 0})
    if audio_pcap_id:
        test_mp3(token, audio_pcap_id, channels=[0, 1, 4, 7])

    # ST 2110-30 audio (2-channel L16)
    test_pcap(token, "ST 2110-30 Audio (L16 2ch)",
        f"{SAMPLE_DIR}/st2110/2110-30/l16_48000_2ch_1ms.pcap",
        {"audio_streams": 1, "video_streams": 0})

    # ST 2110-20 video
    test_pcap(token, "ST 2110-20 Video (1080i59.94)",
        f"{SAMPLE_DIR}/st2110/2110-20/2110-20_1080i5994.pcap",
        {"video_streams": 1, "audio_streams": 0})

    test_pcap(token, "ST 2110-20 Video (720p50)",
        f"{SAMPLE_DIR}/st2110/2110-20/2110-20_720p50.pcap",
        {"video_streams": 1})

    # ST 2110-40 ancillary
    test_pcap(token, "ST 2110-40 Ancillary",
        f"{SAMPLE_DIR}/st2110/2110-40/2110-40_5994i.pcap",
        {"anc_streams": 1})

    # ST 2022-7 (redundant streams — 2 audio streams expected, one per leg)
    test_pcap(token, "ST 2022-7 Audio",
        f"{SAMPLE_DIR}/st2110/2022-7/ST2022-7-Audio.pcap",
        {"audio_streams": 2})

    # SRT — the C++ extractor classifies SRT-wrapped MPEG-TS as 0 RTP streams; just verify upload+analysis
    test_pcap(token, "SRT stream",
        f"{SAMPLE_DIR}/srt/srt_stream.pcap",
        {"analyzed": True})

    # RIST
    test_pcap(token, "RIST stream",
        f"{SAMPLE_DIR}/rist/rist_stream.pcap",
        {"total_streams": 1})

    ok = test_summary()
    sys.exit(0 if ok else 1)
