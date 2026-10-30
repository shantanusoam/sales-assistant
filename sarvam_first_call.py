"""First Sarvam AI Speech-to-Text (Saaras) test script."""
import base64
import io
import os
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

api_key = os.environ["SARVAM_API_KEY"]
client = SarvamAI(api_subscription_key=api_key)

# 1. Generate a quick Hinglish sample WAV in memory so we have real speech to transcribe
tts_resp = client.text_to_speech.convert(
    text="Namaste! Aapka solution thoda expensive lag raha hai, hum abhi Excel use karte hain.",
    language_code="hi-IN",
    model="bulbul:v3",
    speaker="shubh",
)
wav_bytes = base64.b64decode("".join(tts_resp.audios))
wav_file = io.BytesIO(wav_bytes)
wav_file.name = "sample_hinglish.wav"

# 2. Call Sarvam Speech-to-Text (/speech-to-text with saaras:v3 in codemix & translate modes)
stt_codemix = client.speech_to_text.transcribe(
    file=wav_file,
    model="saaras:v3",
    mode="codemix",
)
print("Codemix Transcript:", stt_codemix.transcript)
print("Detected Language:", stt_codemix.language_code)

wav_file.seek(0)
stt_translate = client.speech_to_text.transcribe(
    file=wav_file,
    model="saaras:v3",
    mode="translate",
)
print("English Translation:", stt_translate.transcript)
