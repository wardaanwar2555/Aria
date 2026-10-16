"""Quick check of every service the voice agent depends on.
Run:  python diagnose.py
It tests Groq (LLM + voice), Deepgram (voice) and your LiveKit settings,
saves test audio files, and tells you exactly which part is broken."""
import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env.local")
if not os.path.exists(ENV):
    sys.exit(f"Missing {ENV}  (rename env.example to .env.local)")
load_dotenv(ENV)


def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # network problems, DNS, firewall...
        return 0, str(e).encode()


def show(ok, name, detail=""):
    print(("[ OK ] " if ok else "[FAIL] ") + name + (f"\n       {detail}" if detail else ""))


played = False


def save_and_play(data, filename):
    global played
    path = os.path.join(HERE, filename)
    with open(path, "wb") as f:
        f.write(data)
    print(f"       saved {filename} ({len(data)//1024} KB)")
    if not played and hasattr(os, "startfile"):  # Windows: play it now
        played = True
        os.startfile(path)


print("\n=== LiveKit settings ===")
url = os.getenv("LIVEKIT_URL", "")
show(url.startswith("wss://"), "LIVEKIT_URL", url or "missing - should look like wss://yourproject.livekit.cloud")
show(bool(os.getenv("LIVEKIT_API_KEY")), "LIVEKIT_API_KEY set")
show(bool(os.getenv("LIVEKIT_API_SECRET")), "LIVEKIT_API_SECRET set")

print("\n=== Groq ===")
gkey = os.getenv("GROQ_API_KEY", "")
if not gkey:
    show(False, "GROQ_API_KEY", "missing in .env.local")
else:
    gh = {"Authorization": f"Bearer {gkey}", "Content-Type": "application/json", "User-Agent": "voice-agent-diagnose/1.0"}
    code, body = post(
        "https://api.groq.com/openai/v1/chat/completions", gh,
        {"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": "Say hello in five words."}]},
    )
    if code == 200:
        show(True, "Groq LLM (openai/gpt-oss-20b)", json.loads(body)["choices"][0]["message"]["content"])
    else:
        show(False, "Groq LLM", f"HTTP {code}: {body.decode(errors='ignore')[:300]}")

    code, body = post(
        "https://api.groq.com/openai/v1/audio/speech", gh,
        {"model": "canopylabs/orpheus-v1-english", "voice": "autumn", "input": "Hello, this is a voice test.", "response_format": "wav"},
    )
    if code == 200:
        show(True, "Groq voice (Orpheus)")
        save_and_play(body, "test_groq_voice.wav")
    else:
        show(False, "Groq voice (Orpheus)", f"HTTP {code}: {body.decode(errors='ignore')[:400]}\n"
             "       If this mentions terms: open console.groq.com Playground, pick the Orpheus model and accept the terms.")

print("\n=== Deepgram ===")
dkey = os.getenv("DEEPGRAM_API_KEY", "")
if not dkey:
    show(False, "DEEPGRAM_API_KEY", "not set (optional, but recommended for the voice)")
else:
    code, body = post(
        "https://api.deepgram.com/v1/speak?model=aura-2-thalia-en&encoding=linear16&container=wav",
        {"Authorization": f"Token {dkey}", "Content-Type": "application/json"},
        {"text": "Hello, this is a voice test."},
    )
    if code == 200:
        show(True, "Deepgram voice (Aura 2)")
        save_and_play(body, "test_deepgram_voice.wav")
    else:
        show(False, "Deepgram voice", f"HTTP {code}: {body.decode(errors='ignore')[:300]}")

print("\nDone. A test .wav should have opened and played. If you heard it, that voice works.")
