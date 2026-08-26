import time
import json
import logging
from typing import Optional, List, Dict, Any
from config import settings, logger

class AIRouter:
    """
    Dual-Provider AI Router:
    - Primary: Google Gemini
    - Fallback: Groq (on 429, timeout, quota, or network error)
    """

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

    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False
    ) -> str:
        """
        Sends prompt to Gemini; automatically falls back to Groq if Gemini fails.
        """
        gemini_client = self._get_gemini_client()
        gemini_model = settings.GEMINI_MODEL or "gemini-2.5-flash"
        
        # 1. Try Gemini (Primary)
        if gemini_client:
            try:
                config_kwargs: Dict[str, Any] = {}
                if system_instruction:
                    config_kwargs["system_instruction"] = system_instruction
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"

                response = gemini_client.models.generate_content(
                    model=gemini_model,
                    contents=prompt,
                    config=config_kwargs if config_kwargs else None
                )
                
                if response and response.text:
                    logger.info(f"[AI] Gemini selected ({gemini_model})")
                    return response.text.strip()
            except Exception as e:
                err_msg = str(e)
                logger.warning(f"[AI] Gemini unavailable ({err_msg}) → Groq fallback")
        else:
            logger.info("[AI] Gemini API Key not set → attempting Groq fallback")

        # 2. Try Groq (Fallback)
        groq_client = self._get_groq_client()
        groq_model = settings.GROQ_MODEL or "llama-3.3-70b-versatile"
        
        if groq_client:
            try:
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                kwargs: Dict[str, Any] = {
                    "model": groq_model,
                    "messages": messages,
                    "temperature": 0.2 if json_mode else 0.7,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                chat_completion = groq_client.chat.completions.create(**kwargs)
                content = chat_completion.choices[0].message.content
                if content:
                    logger.info(f"[AI] Groq fallback selected ({groq_model})")
                    return content.strip()
            except Exception as e:
                logger.error(f"[AI] Groq fallback failed: {e}")
        else:
            logger.warning("[AI] Groq API Key not set")

        # 3. Fallback when no external AI keys are configured
        if json_mode:
            return json.dumps({
                "name": "Quick Strategy",
                "timeframe": "5",
                "universe": "NIFTY50",
                "logic": "AND",
                "conditions": []
            })
        return "AI response unavailable. Please check your GEMINI_API_KEY or GROQ_API_KEY environment settings."

ai_router = AIRouter()
