"""Recognize explicit user feedback without guessing arbitrary personal facts."""
from __future__ import annotations

import re
import hashlib
from memory.memory_manager import load_user_profile, update_user_profile

_SHORT = re.compile(r"\b(?:sii|sia|rispondi|parla|risposte?)\s+(?:più|piu)\s+(?:breve|brevi|conciso|concisa|concise|concisi)\b|\b(?:odio|non mi piacciono)\s+le\s+risposte\s+lunghe\b", re.I)
_FORMAL = re.compile(r"\b(?:parla|sii|sia|rispondi)\s+(?:più|piu)\s+formal(?:mente|e)\b", re.I)
_INFORMAL = re.compile(r"\b(?:parla|sii|sia|rispondi)\s+(?:più|piu)\s+informal(?:mente|e)\b", re.I)
_AVOID = re.compile(r"\bnon\s+usare\s+(?:più\s+|piu\s+)?(?:il\s+termine|la\s+parola)\s+['\"«]?([^'\"».,!?]{1,60})['\"»]?", re.I)
_BIRTHDAY = re.compile(r"\b(?:il\s+)?mio\s+compleanno\s+(?:è|e)\s+il\s+(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\b", re.I)
_SUMMARY = re.compile(r"^(?:(?:jarvis|iris)[,\s]+)?cosa\s+hai\s+imparato\s+su\s+di\s+me[?!. ]*$", re.I)
_FACT = re.compile(r"\b(?:il|la|lo|i|gli|le)\s+mi[oaie]\s+([a-zàèéìòù][a-zàèéìòù ]{0,35}?)\s+(?:è|e)\s+(.{1,100}?),\s*non\s+(.+)$", re.I)
_EXPLICIT = re.compile(r"\bricorda\s+che\s+((?:preferisco|odio|non mi piace|mi piace)\s+.+)$", re.I)


def save_explicit_preference(text: str) -> str:
    value = text.strip().rstrip(".!?")
    if not value:
        raise ValueError("La preferenza è vuota.")
    key = "preferenza_" + hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:16]
    update_user_profile("preferences", key, value)
    return "Ho salvato la preferenza nel tuo profilo."


def learn(text: str) -> str | None:
    value = text.strip()
    if re.search(r"\bnon\s+avvisarmi\s+(?:più\s+|piu\s+)?(?:della|per\s+la|sulla)\s+batteria\b", value, re.I):
        update_user_profile("preferences", "low_battery_alert", "disabled")
        return "Ho disattivato gli avvisi proattivi sulla batteria."
    if _SUMMARY.fullmatch(value):
        profile = load_user_profile()
        labels = {"verbosity": "lunghezza risposte", "preferred_tone": "tono"}
        lines = [
            f'{("termine da evitare" if key.startswith("avoid_term") else "preferenza" if key.startswith("preferenza_") else labels.get(key, key.replace("_", " ")))}: {item}'
            for group in ("preferences", "facts") for key, item in profile[group].items()
        ]
        return "Ho imparato: " + "; ".join(lines) if lines else "Non ho ancora salvato preferenze o fatti nel profilo."
    if _SHORT.search(value):
        update_user_profile("preferences", "verbosity", "breve")
        return "Ho salvato la preferenza per risposte brevi."
    if _FORMAL.search(value):
        update_user_profile("preferences", "preferred_tone", "formale")
        return "Ho salvato la preferenza per un tono formale."
    if _INFORMAL.search(value):
        update_user_profile("preferences", "preferred_tone", "informale")
        return "Ho salvato la preferenza per un tono informale."
    match = _AVOID.search(value)
    if match:
        term = match.group(1).strip()
        key = "avoid_term_" + hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:16]
        update_user_profile("preferences", key, term)
        return f"Ho annotato di non usare il termine «{term}»."
    match = _BIRTHDAY.search(value)
    if match and re.search(r"\b(?:no|non|corregg[io]|sbagliat[oa])\b", value, re.I):
        from datetime import date
        months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
        day, month = int(match.group(1)), match.group(2).casefold()
        date(2000, months.index(month) + 1, day)
        update_user_profile("facts", "compleanno", f"{day} {month} (dichiarato dall'utente)")
        return "Hai ragione, ho corretto la mia conoscenza."
    match = _FACT.search(value)
    if match and re.search(r"\b(?:no|corregg[io]|sbagliat[oa])\b", value, re.I):
        key, fact = match.group(1).strip().casefold(), match.group(2).strip()
        update_user_profile("facts", key, f"{fact} (dichiarato dall'utente)")
        return "Hai ragione, ho corretto la mia conoscenza."
    match = _EXPLICIT.search(value)
    if match:
        return save_explicit_preference(match.group(1))
    if re.search(r"\bnon mi piace (?:questo|il tuo|quel) tono\b", value, re.I):
        return "Capito. Che tono preferisci?"
    if re.search(r"\bnon\s+usare\s+quel\s+termine\b", value, re.I):
        return "Quale termine desideri che eviti?"
    return None
