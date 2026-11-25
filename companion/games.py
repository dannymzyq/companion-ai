"""Minijuegos interactivos de voz, escritorio y cámara (N-08).

Juegos disponibles:
- `rps` (Piedra, papel o tijera): el personaje elige al azar, manda la jugada a la interfaz para que haga la cuenta
  1-2-3 con los dedos reales (`fist`, `open`, `peace`) y comenta quién ganó.
- `trivia`: lanza una pregunta curiosa con opciones y evalúa tu respuesta.
- `twenty` (20 preguntas): piensa en algo secreto y responde sí/no/casi hasta que lo adivines.
- `ispy` (Veo-veo): si compartes pantalla o cámara, elige algo visible para que adivines qué es.
"""
import random
import re

from .text_utils import plain

RPS_CHOICES = ("piedra", "papel", "tijera")
_BEATS = {"piedra": "tijera", "papel": "piedra", "tijera": "papel"}


def parse_rps(text: str | None) -> str | None:
    if not text:
        return None
    t = plain(text)
    for opt in RPS_CHOICES:
        if re.search(rf"\b{opt}s?\b", t):
            return opt
    return None


def play_rps(user_choice: str | None = None, *, user_name: str = "tú") -> tuple[str, str | None, str, str]:
    """Devuelve `(pick_companion, user_choice_norm, outcome, prompt_instruction)`."""
    pick = random.choice(RPS_CHOICES)
    uchoice = parse_rps(user_choice)
    if not uchoice:
        instr = (
            f"({user_name} quiere jugar a Piedra, papel o tijera contigo. En pantalla acabas de sacar «{pick}» "
            f"tras contar 1, 2, 3. Di con energía «¡Piedra, papel o tijera… {pick}!» y pregúntale qué sacó.)"
        )
        return pick, None, "reveal", instr
    if pick == uchoice:
        outcome = "empate"
        verdict = f"Empatasteis: ambos sacasteis «{pick}». Pídele la revancha con humor."
        emo = "sorprendida"
    elif _BEATS[pick] == uchoice:
        outcome = "companion"
        verdict = f"Ganaste tú: sacaste «{pick}» contra su «{uchoice}». Celébralo con tu personalidad."
        emo = "emocionada"
    else:
        outcome = "user"
        verdict = f"Ganó {user_name}: sacó «{uchoice}» contra tu «{pick}». Reacciona con deportividad (o pique gracioso)."
        emo = "feliz"
    instr = f"(Juego Piedra, papel o tijera: {verdict} Empieza con [emo:{emo}] y sé breve, una o dos frases.)"
    return pick, uchoice, outcome, instr


def game_instruction(game: str, *, user_name: str, has_vision: bool = False) -> str | None:
    g = plain(game)
    if g == "trivia":
        return (
            f"({user_name} quiere jugar una ronda rápida de Trivia contigo. Hazle UNA pregunta entretenida y no obvia "
            "con 3 opciones cortas —A, B y C— adaptada a tus gustos o cultura general, sin revelar la respuesta aún.)"
        )
    if g in ("twenty", "20_preguntas", "adivina"):
        return (
            f"({user_name} quiere jugar a las 20 preguntas contigo. Elige en silencio un objeto, animal o personaje "
            "conocido, no lo digas y anímale en una frase corta a hacerte la primera pregunta de sí o no.)"
        )
    if g in ("ispy", "veo_veo"):
        if not has_vision:
            return (
                f"({user_name} quiere jugar al Veo-veo, pero ahora mismo no está compartiendo pantalla ni cámara. "
                "Pídele con simpatía en una frase que active la cámara o comparta la pantalla para poder mirar.)"
            )
        return (
            f"({user_name} quiere jugar al Veo-veo con lo que ves ahora mismo en su imagen. Fíjate en un objeto o "
            "color real que se distinga en la captura, di «Veo, veo… una cosita de color…» o una pista corta sin "
            "decir qué es, y deja que adivine.)"
        )
    return None
