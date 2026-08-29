import asyncio
from typing import Optional
from config import settings, logger

class AIRouter:
    def __init__(self): self._gemini=None; self._groq=None
    def _gemini_client(self):
        if self._gemini is None and settings.GEMINI_API_KEY:
            from google import genai
            self._gemini=genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini
    def _groq_client(self):
        if self._groq is None and settings.GROQ_API_KEY:
            from groq import Groq
            self._groq=Groq(api_key=settings.GROQ_API_KEY)
        return self._groq
    def _gemini_call(self,prompt,system):
        c=self._gemini_client()
        if not c: raise RuntimeError('Gemini not configured')
        cfg={'system_instruction':system} if system else None
        r=c.models.generate_content(model=settings.GEMINI_MODEL,contents=prompt,config=cfg)
        if not r or not r.text: raise RuntimeError('empty Gemini response')
        logger.info('[AI] Gemini selected (%s)',settings.GEMINI_MODEL); return r.text.strip()
    def _gemini_file_call(self,data,mime,prompt,system):
        c=self._gemini_client()
        if not c: raise RuntimeError('Gemini not configured')
        from google.genai import types
        part=types.Part.from_bytes(data=data,mime_type=mime)
        cfg={'system_instruction':system}
        r=c.models.generate_content(model=settings.GEMINI_MODEL,contents=[prompt,part],config=cfg)
        if not r or not r.text: raise RuntimeError('empty Gemini file response')
        logger.info('[AI] Gemini file parser selected (%s)',settings.GEMINI_MODEL); return r.text.strip()
    def _groq_call(self,prompt,system):
        c=self._groq_client()
        if not c: raise RuntimeError('Groq not configured')
        msgs=[]
        if system:msgs.append({'role':'system','content':system})
        msgs.append({'role':'user','content':prompt})
        r=c.chat.completions.create(model=settings.GROQ_MODEL,messages=msgs,temperature=.2)
        logger.info('[AI] Groq fallback selected (%s)',settings.GROQ_MODEL); return r.choices[0].message.content.strip()
    async def answer(self,prompt:str,system:Optional[str]=None):
        try:return await asyncio.wait_for(asyncio.to_thread(self._gemini_call,prompt,system),15)
        except Exception as e:logger.warning('[AI] Gemini unavailable/slow: %s',e)
        try:return await asyncio.wait_for(asyncio.to_thread(self._groq_call,prompt,system),8)
        except Exception as e:logger.error('[AI] Groq failed: %s',e)
        return 'AI response unavailable right now. Please try again.'
    async def answer_file(self,data:bytes,mime:str,prompt:str,system:Optional[str]=None):
        return await asyncio.wait_for(asyncio.to_thread(self._gemini_file_call,data,mime,prompt,system),25)

    async def inspect_image(self,data:bytes,mime:str,prompt:str,system:Optional[str]=None):
        # Vision is Gemini-only in this build. Never fabricate an image interpretation.
        return await self.answer_file(data,mime,prompt,system)

ai_router=AIRouter()
