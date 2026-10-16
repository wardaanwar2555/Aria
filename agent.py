import asyncio
import json
import logging
import os
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, RunContext, function_tool
from livekit.plugins import deepgram, groq, silero

# Load LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, GROQ_API_KEY
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
if not os.path.exists(ENV_PATH):
    raise SystemExit(
        f"Missing {ENV_PATH}\n"
        "Rename env.example to .env.local (same folder as agent.py) and fill in your keys."
    )
load_dotenv(ENV_PATH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("my-voice-agent")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a friendly AI voice assistant. "
                "Speak clearly and naturally. "
                "Keep answers short, usually one to three sentences. "
                "Ask only one question at a time. "
                "Do not use emojis, markdown, or bullet points, because your "
                "answers are spoken aloud. "
                "If you do not know something, say so honestly."
            )
        )

    # Example tool: the LLM can call this when the user asks for the time.
    # Add more @function_tool methods here to call APIs, databases, etc.
    @function_tool
    async def get_current_time(self, context: RunContext) -> str:
        """Get the current local date and time. Use when the user asks what time or date it is."""
        return datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


PREFERRED_LLMS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
]


def pick_groq_model() -> str:
    """Use GROQ_LLM_MODEL if set; otherwise ask Groq which models your key can use."""
    forced = os.getenv("GROQ_LLM_MODEL")
    if forced:
        return forced
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "User-Agent": "voice-agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            available = {m["id"] for m in json.loads(r.read())["data"]}
        for m in PREFERRED_LLMS:
            if m in available:
                return m
        logger.warning("None of the preferred models are available. Set GROQ_LLM_MODEL in .env.local. Available: %s", sorted(available))
    except Exception as e:
        logger.warning("Could not list Groq models (%r); using default", e)
    return PREFERRED_LLMS[0]


async def tts_works(tts_instance, name: str) -> bool:
    """Synthesize a short phrase to prove this voice really produces audio."""
    try:
        stream = tts_instance.synthesize("Hello, this is a voice test.")
        samples = 0
        async for ev in stream:
            samples += ev.frame.samples_per_channel
        await stream.aclose()
        if samples > 0:
            logger.info("VOICE TEST OK: %s produced %d audio samples", name, samples)
            return True
        logger.error("VOICE TEST FAILED: %s returned no audio", name)
    except Exception as e:
        logger.error("VOICE TEST FAILED: %s -> %r", name, e)
    return False


async def pick_tts():
    """Try Deepgram (if key set), then Groq Orpheus; use the first one that really makes sound."""
    candidates = []
    if os.getenv("DEEPGRAM_API_KEY"):
        candidates.append(("Deepgram Aura", lambda: deepgram.TTS(model="aura-2-thalia-en")))
    candidates.append(("Groq Orpheus", lambda: groq.TTS(model="canopylabs/orpheus-v1-english", voice="autumn")))
    for name, make in candidates:
        instance = make()
        if await tts_works(instance, name):
            logger.info("USING VOICE: %s", name)
            return instance
    logger.error("NO WORKING VOICE. Add DEEPGRAM_API_KEY to .env.local or accept the Groq Orpheus terms.")
    return candidates[0][1]()


async def entrypoint(ctx: agents.JobContext):
    llm_model = await asyncio.to_thread(pick_groq_model)
    logger.info("LLM: Groq %s", llm_model)
    tts_instance = await pick_tts()
    session = AgentSession(
        stt=groq.STT(model="whisper-large-v3-turbo"),   # speech -> text
        llm=groq.LLM(model=llm_model),                  # the "brain"
        tts=tts_instance,                               # text -> speech
        vad=silero.VAD.load(),                          # detects when you start/stop talking
    )

    # Print any STT / LLM / TTS failure clearly in the terminal
    @session.on("error")
    def _on_error(ev):
        logger.error("PIPELINE ERROR: %r", getattr(ev, "error", ev))

    @session.on("user_input_transcribed")
    def _on_user(ev):
        if ev.is_final:
            logger.info("HEARD YOU: %s", ev.transcript)

    @session.on("conversation_item_added")
    def _on_item(ev):
        if getattr(ev.item, "role", None) == "assistant":
            logger.info("AGENT SAYS: %s", ev.item.text_content)

    @session.on("agent_state_changed")
    def _on_state(ev):
        logger.info("agent state: %s -> %s", ev.old_state, ev.new_state)

    await session.start(room=ctx.room, agent=Assistant())

    try:
        await session.generate_reply(
            instructions="Greet the user briefly and ask how you can help."
        )
    except Exception as e:
        logger.error("GREETING FAILED: %r", e)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))