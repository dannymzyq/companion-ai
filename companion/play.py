"""Juegos con el cuerpo del personaje (17 nov 2026): «¿puedes bailar?», «salta», «date una vuelta», «duérmete»…

El modelo ya conoce estas peticiones (prompt.py: la etiqueta [gesto:…]), pero los modelos pequeños a veces responden
«¡claro!» sin la etiqueta, o dicen que no pueden. `guess` reconoce en las palabras del usuario una petición clara
(un imperativo, o «puedes / podrías / quieres / quiero que…» + infinitivo o subjuntivo) y la sesión añade el gesto a
la primera frase de la respuesta si el modelo no lo puso. Solo mueve al personaje en pantalla: nada se ejecuta en la PC.
"""
import re
import unicodedata

# Peticiones que se entienden como pedirle algo («¿puedes…?», «quiero que…»); con ellas vale el infinitivo o el
# subjuntivo («¿puedes bailar?», «quiero que bailes»).
_ASK = re.compile(r"\b(puedes|podrias|quieres|querrias|sabes|vas a|me (gustaria|encantaria) que|quiero que|a ver si|"
                  r"te animas a|hazme el favor de|por que no)\b")

# gesto → (imperativos, con petición). Texto sin acentos y en minúsculas.
_MOVES = {
    "bailar": (r"\bbail(a|ame|anos|alo|emos)\b|\bmueve el esqueleto\b",
               r"\b(bailar(me|nos|lo)?|bailes|bailas)\b"),
    "saltar": (r"\b(salta|saltame|brinca|da un salto|pega un salto)\b",
               r"\b(saltar|brincar|dar un salto|saltes|brinques)\b"),
    "girar": (r"\b(gira|girate|da(te)? (una|la) vuelta)\b",
              r"\b(girar(te)?|dar(te)? (una|la) vuelta|gires|(te )?des (una|la) vuelta)\b"),
    "estirarse": (r"\b(estirate|desperezate)\b",
                  r"\b(estirarte|desperezarte|te estires)\b"),
    "hechizo": (r"\bhaz(me)? (un |una )?(hechizo|magia|truco de magia)\b|\blanza un hechizo\b",
                r"\b(hacer(me)?|hagas) (un |una )?(hechizo|magia|truco de magia)\b|\blanzar un hechizo\b"),
    "tararear": (r"\b(tararea|canta(me|nos)?)\b",
                 r"\b(tararear|cantar(me|nos)?|cantes|tararees)\b"),
    "saludar": (r"\b(saluda|saludame|saludanos)\b",
                r"\b(saludar(me|nos)?|saludes)\b"),
    "aplaudir": (r"\b(aplaude|aplaudeme)\b",
                 r"\b(aplaudir(me)?|aplaudas)\b"),
    "reverencia": (r"\bhaz(me)? (una )?reverencia\b",
                   r"\b(hacer(me)?|hagas) (una )?reverencia\b"),
    "pulgar": (r"\b(pulgar(es)? (arriba|hacia arriba)|levanta el pulgar)\b",
               r"\blevantar el pulgar\b"),
    "paz": (r"\bhaz(me)? (el signo de |la senal de )?(la )?(paz|uve|v)\b",
            r"\b(hacer(me)?|hagas) (el signo de |la senal de )?(la )?(paz|uve|v)\b"),
    "beber": (r"\b(bebe|bebete|tomate) (algo|agua|un te|un cafe)\b",
              r"\b(beber|tomar(te)?|bebas) (algo|agua|un te|un cafe)\b"),
    # «A dormir» solo como orden suelta (al principio o tras un signo): «me voy a dormir» habla de quien escribe.
    "dormir": (r"\b(duermete|duerme un poco|echate una siesta|tomate una siesta|ve a dormir)\b|(^|[,.!¡]\s*)(a dormir|a la cama)\b",
               r"\b(dormir(te)?( un poco)?|echarte una siesta|tomar(te)? una siesta|te duermas)\b"),
}
_COMPILED = {k: (re.compile(i), re.compile(f)) for k, (i, f) in _MOVES.items()}
# Negaciones que anulan la petición («no bailes», «no te duermas»).
_NOT = re.compile(r"\b(no|nunca|ni)\s+(te\s+)?(bail|salt|gir|duerm|cant|tarar|estir|aplaud|salud)")


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def guess(text: str | None) -> str | None:
    """El gesto que el usuario pide claramente (bailar, saltar, girar, dormir…) o None."""
    if not text:
        return None
    t = _plain(text).strip()
    if _NOT.search(t):
        return None
    ask = _ASK.search(t)
    best = None
    for name, (imp, asked) in _COMPILED.items():
        m = imp.search(t) or (asked.search(t, ask.end()) if ask else None)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None
