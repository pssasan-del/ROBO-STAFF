import asyncio
import json
from typing import Optional, Dict, Any
from config import settings, logger


class AIRouter:
    """Gemini primary + Groq fallback router."""

    def __init__(self):
        self._gemini_client = None
        self._groq_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None and settings.GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.warning(f"[AI] Failed to initialize Gemini client: {e}")
        return self._gemini_client

    def _get_groq_client(self):
        if self._groq_client is None and settings.GROQ_API_KEY:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                logger.warning(f"[AI] Failed to initialize Groq client: {e}")
        return self._groq_client

    def _gemini_response(self, prompt: str, system_instruction: Optional[str], json_mode: bool) -> str:
        client = self._get_gemini_client()
        if not client:
            raise RuntimeError("Gemini API key not configured")
        config_kwargs: Dict[str, Any] = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL or "gemini-3.5-flash-lite",
            contents=prompt,
            config=config_kwargs if config_kwargs else None,
        )
        if not response or not response.text:
            raise RuntimeError("Gemini returned an empty response")
        logger.info(f"[AI] Gemini selected ({settings.GEMINI_MODEL})")
        return response.text.strip()

    def _groq_response(self, prompt: str, system_instruction: Optional[str], json_mode: bool) -> str:
        client = self._get_groq_client()
        if not client:
            raise RuntimeError("Groq API key not configured")
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        kwargs: Dict[str, Any] = {
            "model": settings.GROQ_MODEL or "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.2 if json_mode else 0.55,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        completion = client.chat.completions.create(**kwargs)
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("Groq returned an empty response")
        logger.info(f"[AI] Groq fallback selected ({settings.GROQ_MODEL})")
        return content.strip()

    def generate_response(self, prompt: str, system_instruction: Optional[str] = None, json_mode: bool = False) -> str:
        """Synchronous API used by strategy parsing/tests."""
        try:
            return self._gemini_response(prompt, system_instruction, json_mode)
        except Exception as e:
            logger.warning(f"[AI] Gemini unavailable ({e}) → Groq fallback")
        try:
            return self._groq_response(prompt, system_instruction, json_mode)
        except Exception as e:
            logger.error(f"[AI] Groq fallback failed: {e}")
        if json_mode:
            return json.dumps({"name":"Quick Strategy","timeframe":"5","universe":"NIFTY50","logic":"AND","conditions":[]})
        return "AI response unavailable. Please check Gemini/Groq configuration."

    async def generate_response_async(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        gemini_timeout: float = 12.0,
        groq_timeout: float = 10.0,
    ) -> str:
        """Non-blocking Telegram AI path. Falls back quickly if Gemini is slow."""
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._gemini_response, prompt, system_instruction, json_mode),
                timeout=gemini_timeout,
            )
            return result
        except Exception as e:
            logger.warning(f"[AI] Gemini async unavailable/slow ({e}) → Groq fallback")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._groq_response, prompt, system_instruction, json_mode),
                timeout=groq_timeout,
            )
        except Exception as e:
            logger.error(f"[AI] Groq async fallback failed: {e}")
        return "AI response unavailable right now. Please try again in a moment."


ai_router = AIRouter()
