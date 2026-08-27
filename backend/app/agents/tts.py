import base64

from groq import Groq

from app.config import get_settings


def synthesize_speech(text: str) -> bytes:
    """Synthesize narration to WAV bytes via Groq PlayAI TTS."""
    s = get_settings()
    client = Groq(api_key=s.groq_api_key)
    response = client.audio.speech.create(
        model=s.tts_model,
        voice=s.tts_voice,
        input=text,
        response_format="wav",
    )
    return base64.b64decode(base64.b64encode(response.read()))
