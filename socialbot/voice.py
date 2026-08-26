"""Voice I/O for SocialBot command center.

STT/TTS backends the operator controls:
  - local: speech_recognition + pyttsx3 when installed
  - offline fallback: text-only

No third-party account theft. No cracked keys.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("socialbot.voice")


class VoiceEngine:
    def __init__(self, store=None):
        self.store = store
        self._stt = None
        self._tts = None
        self._init_local()

    def _init_local(self) -> None:
        try:
            import speech_recognition as sr
            self._stt = sr
        except Exception:
            self._stt = None
        try:
            import pyttsx3
            self._tts = pyttsx3.init()
        except Exception:
            self._tts = None

    def capabilities(self) -> Dict[str, Any]:
        return {
            "stt_local": self._stt is not None,
            "tts_local": self._tts is not None,
            "chatgpt_linked": self._chatgpt_ok(),
            "mode": "local" if self._stt else "text-fallback",
        }

    def _chatgpt_ok(self) -> bool:
        if not self.store:
            return False
        try:
            from .chatgpt_oauth import ChatGPTOAuth
            return ChatGPTOAuth(store=self.store).is_authenticated()
        except Exception:
            return False

    def listen_once(self, timeout: float = 5.0, phrase_time_limit: float = 15.0) -> str:
        if not self._stt:
            raise RuntimeError(
                "speech_recognition not installed. pip install SpeechRecognition pyaudio"
            )
        sr = self._stt
        r = sr.Recognizer()
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.4)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        try:
            return r.recognize_sphinx(audio)
        except Exception:
            pass
        try:
            return r.recognize_google(audio)
        except Exception as e:
            raise RuntimeError(f"STT failed: {e}") from e

    def speak(self, text: str) -> None:
        if not text:
            return
        if self._tts:
            self._tts.say(text)
            self._tts.runAndWait()
            return
        logger.info("TTS unavailable — would speak: %s", text[:120])

    def handle_command(self, text: str) -> Dict[str, Any]:
        from .desktop_skills import DesktopSkills
        return DesktopSkills().run(text, store=self.store)
