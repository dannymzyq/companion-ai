"""Mide cuánto tarda cada modelo en dar la primera frase (lo que más pesa en la latencia de la conversación).

    .venv\\Scripts\\python.exe scripts\\herramientas\\medir_llm.py gemini-3.6-flash:minimal gemini-3.5-flash-lite:minimal
    .venv\\Scripts\\python.exe scripts\\herramientas\\medir_llm.py local/gemma4:e4b-it-qat local/gemma4:e2b-it-qat
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from companion import llm  # noqa: E402
from companion.config import settings  # noqa: E402
from companion.prompt import build_system_prompt, load_persona, local_time, sampling_for  # noqa: E402
from companion.tags import TagStream  # noqa: E402

PREGUNTAS = ["¿Qué me recomiendas para concentrarme esta tarde?", "Oye, ¿cuánto es quince por doce?",
             "Cuéntame algo curioso sobre el café."]


async def medir(model: str, reasoning: str):
    if model.startswith("local/"):                         # p. ej. local/gemma4:e4b-it-qat → Ollama en esta PC
        settings.llm_provider, settings.ollama_model, settings.ollama_fallback = "local", model[6:], []
    else:
        settings.llm_provider, settings.gemini_model, settings.gemini_reasoning = "gemini", model, reasoning
    persona = load_persona(settings.persona_path)
    system = build_system_prompt(persona, user_name=settings.user_name, memories=[], adult=False)
    for pregunta in PREGUNTAS:
        parser, t0, primero, frase = TagStream(), time.perf_counter(), None, None
        try:
            async for piece in llm.stream_chat([{"role": "system", "content": system},
                                                {"role": "user", "content": pregunta}], sampling_for(persona)):
                primero = primero or time.perf_counter() - t0
                if frase is None and parser.feed(piece):
                    frase = time.perf_counter() - t0
            total = time.perf_counter() - t0
            print(f"{model:24} {reasoning or '-':8} primer texto {primero:.2f}s · primera frase {(frase or total):.2f}s · total {total:.2f}s")
        except llm.LLMError as e:
            print(f"{model:24} {reasoning or '-':8} ERROR: {e}")
            return
        await asyncio.sleep(1.0)


async def main():
    for spec in sys.argv[1:] or ["gemini-3.6-flash:minimal"]:
        model, _, reasoning = (spec, "", "") if spec.startswith("local/") else spec.partition(":")
        await medir(model, reasoning)


if __name__ == "__main__":
    asyncio.run(main())
