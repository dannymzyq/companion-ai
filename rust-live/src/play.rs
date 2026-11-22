use regex::Regex;
use std::sync::OnceLock;

pub fn plain(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .map(|c| match c {
            'á' | 'à' | 'ä' | 'â' => 'a',
            'é' | 'è' | 'ë' | 'ê' => 'e',
            'í' | 'ì' | 'ï' | 'î' => 'i',
            'ó' | 'ò' | 'ö' | 'ô' => 'o',
            'ú' | 'ù' | 'ü' | 'û' => 'u',
            'ñ' => 'n',
            other => other,
        })
        .collect()
}

struct CompiledMoves {
    ask: Regex,
    not_re: Regex,
    moves: Vec<(&'static str, Regex, Regex)>,
}

fn compiled() -> &'static CompiledMoves {
    static CELL: OnceLock<CompiledMoves> = OnceLock::new();
    CELL.get_or_init(|| {
        let raw: &[(&str, &str, &str)] = &[
            ("sensual", r"\b(baila(me)? (algo )?(sensual|sexy|lento)|haz(me)? un baile (sensual|sexy))\b",
                        r"\b(bailar(me)? (algo )?(sensual|sexy|lento)|bailes (algo )?(sensual|sexy)|hacer(me)? un baile (sensual|sexy))\b"),
            ("bailar", r"\bbail(a|ame|anos|alo|emos)\b|\bmueve el esqueleto\b",
                       r"\b(bailar(me|nos|lo)?|bailes|bailas)\b"),
            ("saltar", r"\b(salta|saltame|brinca|da un salto|pega un salto)\b",
                       r"\b(saltar|brincar|dar un salto|saltes|brinques)\b"),
            ("girar", r"\b(gira|girate|da(te)? (una|la) vuelta)\b",
                      r"\b(girar(te)?|dar(te)? (una|la) vuelta|gires|(te )?des (una|la) vuelta)\b"),
            ("ninja", r"\b(haz(me)? (un )?salto ninja|salta como (un )?ninja)\b",
                      r"\b(hacer(me)?|hagas) (un )?salto ninja\b"),
            ("zombi", r"\b(haz(te)? (de |la |el )?zombie?|camina como (un )?zombie?)\b",
                      r"\b(hacer(te)? (de |la |el )?zombie?|hagas (de |la |el )?zombie?)\b"),
            ("posar", r"\b(posa|haz(me)? una pose( sexy)?|ponte sexy)\b",
                      r"\b(posar|poses|hacer(me)? una pose|ponerte sexy)\b"),
            ("beso", r"\b(lanza(me)? un beso|manda(me)? un beso|dame un beso)\b",
                     r"\b(lanzar(me)? un beso|mandar(me)? un beso|me lances un beso|me mandes un beso)\b"),
            ("melena", r"\b(mueve el pelo|echate el pelo( atras)?)\b",
                       r"\b(mover el pelo|echarte el pelo( atras)?)\b"),
            ("boxear", r"\b(boxea|haz(me)? boxeo|da(me)? (unos )?punetazos al aire)\b",
                       r"\b(boxear|boxees|hacer boxeo)\b"),
            ("estirarse", r"\b(estirate|desperezate)\b",
                          r"\b(estirarte|desperezarte|te estires)\b"),
            ("hechizo", r"\bhaz(me)? (un |una )?(hechizo|magia|truco de magia)\b|\blanza un hechizo\b",
                        r"\b(hacer(me)?|hagas) (un |una )?(hechizo|magia|truco de magia)\b|\blanzar un hechizo\b"),
            ("tararear", r"\b(tararea|canta(me|nos)?)\b",
                         r"\b(tararear|cantar(me|nos)?|cantes|tararees)\b"),
            ("saludar", r"\b(saluda|saludame|saludanos)\b",
                        r"\b(saludar(me|nos)?|saludes)\b"),
            ("aplaudir", r"\b(aplaude|aplaudeme)\b",
                         r"\b(aplaudir(me)?|aplaudas)\b"),
            ("reverencia", r"\bhaz(me)? (una )?reverencia\b",
                           r"\b(hacer(me)?|hagas) (una )?reverencia\b"),
            ("pulgar", r"\b(pulgar(es)? (arriba|hacia arriba)|levanta el pulgar)\b",
                       r"\blevantar el pulgar\b"),
            ("paz", r"\bhaz(me)? (el signo de |la senal de )?(la )?(paz|uve|v)\b",
                    r"\b(hacer(me)?|hagas) (el signo de |la senal de )?(la )?(paz|uve|v)\b"),
            ("beber", r"\b(bebe|bebete|tomate) (algo|agua|un te|un cafe)\b",
                      r"\b(beber|tomar(te)?|bebas) (algo|agua|un te|un cafe)\b"),
            ("dormir", r"\b(duermete|duerme un poco|echate una siesta|tomate una siesta|ve a dormir)\b|(^|[,.!¡]\s*)(a dormir|a la cama)\b",
                       r"\b(dormir(te)?( un poco)?|echarte una siesta|tomar(te)? una siesta|te duermas)\b"),
        ];
        CompiledMoves {
            ask: Regex::new(r"\b(puedes|podrias|quieres|querrias|sabes|vas a|me (gustaria|encantaria) que|quiero que|a ver si|te animas a|hazme el favor de|por que no)\b").unwrap(),
            not_re: Regex::new(r"\b(no|nunca|ni)\s+(te\s+)?(bail|salt|gir|duerm|cant|tarar|estir|aplaud|salud)").unwrap(),
            moves: raw
                .iter()
                .map(|(k, i, f)| (*k, Regex::new(i).unwrap(), Regex::new(f).unwrap()))
                .collect(),
        }
    })
}

pub fn guess(text: &str) -> Option<&'static str> {
    let t = plain(text);
    let t = t.trim();
    if t.is_empty() {
        return None;
    }
    let c = compiled();
    if c.not_re.is_match(t) {
        return None;
    }
    let ask_end = c.ask.find(t).map(|m| m.end());
    let mut best: Option<(usize, &'static str)> = None;
    for (name, imp, asked) in &c.moves {
        let m = imp.find(t).or_else(|| {
            ask_end.and_then(|pos| asked.find(&t[pos..]).map(|mm| (mm.start() + pos, mm.end() + pos)))
                .map(|_| imp.find(t))
                .flatten()
        });
        let start = if let Some(mm) = imp.find(t) {
            Some(mm.start())
        } else if let Some(pos) = ask_end {
            asked.find(&t[pos..]).map(|mm| mm.start() + pos)
        } else {
            None
        };
        let _ = m;
        if let Some(pos) = start {
            if best.map(|(b, _)| pos < b).unwrap_or(true) {
                best = Some((pos, *name));
            }
        }
    }
    best.map(|(_, name)| name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_gestures_and_negations() {
        assert_eq!(guess("¿puedes bailar un poco?"), Some("bailar"));
        assert_eq!(guess("baila algo sensual"), Some("sensual"));
        assert_eq!(guess("no bailes ahora"), None);
        assert_eq!(guess("salta!"), Some("saltar"));
    }
}
