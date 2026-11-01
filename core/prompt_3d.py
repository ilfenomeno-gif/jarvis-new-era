"""Prompt preparation for the local text-to-3D pipeline. Pure Python, no torch.

SD-Turbo understands English far better than Italian, so an Italian prompt is translated
word by word with a small built-in dictionary of common objects (offline, no extra model).
It is a best-effort fallback: the generate_3d_model tool also asks the LLM to pass an
English prompt, which is the primary translation path.
"""
from __future__ import annotations

import re

IMAGE_SUFFIX = "isolated on a solid white background, studio lighting, high quality, 3D asset"
CLEAN_SUFFIX = "clean geometry, single object, no overlapping parts, sharp edges, solid structure"
VIEW_HINT = "three-quarter view"

# Hollow or boxy furniture comes out as warped blobs unless the shape is spelled out.
BOXY_HINTS = {
    "wardrobe": "a closed wooden wardrobe, simple box shape",
    "cabinet": "a closed wooden cabinet, simple box shape",
    "fridge": "a closed refrigerator, simple box shape",
    "bookcase": "a wooden bookcase, simple box shape",
    "crate": "a closed wooden crate, simple box shape",
    "box": "a closed box, simple box shape",
}

ARTICLES = {"un", "uno", "una", "il", "lo", "la", "l", "i", "gli", "le", "un'"}
FUNCTION_WORDS = {"di": "of", "del": "of the", "della": "of the", "dei": "of the", "con": "with",
                  "senza": "without", "e": "and", "in": "in", "su": "on", "per": "for", "a": "a"}

NOUNS = {
    "sedia": "chair", "sedie": "chairs", "poltrona": "armchair", "divano": "sofa", "tavolo": "table",
    "tavolino": "coffee table", "scrivania": "desk", "letto": "bed", "lampada": "lamp", "armadio": "wardrobe",
    "libreria": "bookcase", "scaffale": "shelf", "panca": "bench", "sgabello": "stool", "specchio": "mirror",
    "spada": "sword", "scudo": "shield", "elmo": "helmet", "casco": "helmet", "corona": "crown", "anello": "ring",
    "macchina": "car", "auto": "car", "automobile": "car", "moto": "motorcycle", "motocicletta": "motorcycle",
    "bicicletta": "bicycle", "camion": "truck", "autobus": "bus", "treno": "train", "nave": "ship",
    "barca": "boat", "aereo": "airplane", "elicottero": "helicopter", "razzo": "rocket", "astronave": "spaceship",
    "motore": "engine", "turbina": "turbine", "ingranaggio": "gear", "robot": "robot", "drone": "drone",
    "scheda": "card", "video": "video", "processore": "processor", "computer": "computer", "telefono": "phone",
    "cellulare": "mobile phone", "orologio": "clock", "chitarra": "guitar", "violino": "violin",
    "pianoforte": "piano", "tazza": "mug", "bicchiere": "glass", "bottiglia": "bottle", "vaso": "vase",
    "piatto": "plate", "coltello": "knife", "forchetta": "fork", "cucchiaio": "spoon", "pentola": "pot",
    "casa": "house", "castello": "castle", "torre": "tower", "ponte": "bridge", "chiesa": "church",
    "albero": "tree", "fiore": "flower", "pianta": "plant", "roccia": "rock", "montagna": "mountain",
    "cane": "dog", "gatto": "cat", "cavallo": "horse", "uccello": "bird", "pesce": "fish", "drago": "dragon",
    "dinosauro": "dinosaur", "orso": "bear", "leone": "lion", "mela": "apple", "pizza": "pizza",
    "torta": "cake", "cuore": "heart", "cranio": "skull", "teschio": "skull", "uomo": "man", "donna": "woman",
    "statua": "statue", "zaino": "backpack", "borsa": "bag", "scarpa": "shoe", "cappello": "hat",
    "ombrello": "umbrella", "chiave": "key", "porta": "door", "finestra": "window", "scala": "staircase",
    "cassa": "crate", "scatola": "box", "barile": "barrel", "bomba": "bomb", "pistola": "pistol",
    "fucile": "rifle", "carro": "cart", "carrozza": "carriage", "tenda": "tent", "fontana": "fountain",
}
ADJECTIVES = {
    "semplice": "simple", "piccolo": "small", "piccola": "small", "grande": "large", "grosso": "big",
    "alto": "tall", "alta": "tall", "basso": "low", "lungo": "long", "lunga": "long", "vecchio": "old",
    "vecchia": "old", "antico": "antique", "antica": "antique", "moderno": "modern", "moderna": "modern",
    "futuristico": "futuristic", "futuristica": "futuristic", "medievale": "medieval", "rotondo": "round",
    "rotonda": "round", "quadrato": "square", "di legno": "wooden", "legno": "wood", "ferro": "iron",
    "metallo": "metal", "oro": "gold", "argento": "silver", "vetro": "glass", "pietra": "stone",
    "rosso": "red", "rossa": "red", "blu": "blue", "verde": "green", "giallo": "yellow", "gialla": "yellow",
    "nero": "black", "nera": "black", "bianco": "white", "bianca": "white", "luminoso": "glowing",
    "olografico": "holographic", "laser": "laser", "elettrico": "electric", "elettrica": "electric",
    "a reazione": "jet", "da corsa": "racing", "sportiva": "sports", "sportivo": "sports",
}
PHRASES = {
    "a reazione": "jet", "da corsa": "racing", "di legno": "wooden", "di metallo": "metal",
    "di ferro": "iron", "di vetro": "glass", "di pietra": "stone", "d'oro": "golden", "di oro": "golden",
    "d'argento": "silver", "scheda video": "graphics card", "spada laser": "laser sword",
    "crea un ologramma di": "", "crea un ologramma": "", "crea l'ologramma di": "", "crea": "",
    "fammi": "", "genera": "", "costruisci": "", "mostrami": "", "voglio": "", "ologramma di": "",
}
NOUNS.update({"cuscino": "cushion", "ruota": "wheel", "ruote": "wheels", "gamba": "leg", "gambe": "legs",
              "braccio": "arm", "ala": "wing", "ali": "wings", "coda": "tail", "occhio": "eye"})

ITALIAN_HINTS = ARTICLES | {"di", "del", "della", "con", "senza", "per", "che", "mi", "crea", "fammi",
                            "voglio", "ologramma", "oggetto", "genera", "mostrami", "costruisci"}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-zàèéìòù]+", text.lower().replace("'", " "))


def looks_italian(text: str) -> bool:
    words = tokens(text)
    if not words:
        return False
    if any(ch in text for ch in "àèéìòù"):
        return True
    hits = sum(1 for word in words if word in ITALIAN_HINTS or word in NOUNS or word in ADJECTIVES)
    english_hits = sum(1 for word in words if word in {"a", "an", "the", "of", "with", "and", "wooden", "simple"})
    return hits > english_hits and hits >= 1


def _apply_phrases(text: str) -> str:
    lowered = " " + " ".join(text.lower().replace("'", "' ").split()) + " "
    for phrase in sorted(PHRASES, key=len, reverse=True):
        lowered = lowered.replace(" " + phrase.replace("'", "' ") + " ", " " + PHRASES[phrase] + " ")
    return lowered.replace("' ", " ").strip()


def to_english(text: str) -> tuple[str, bool]:
    """(english prompt, True when it was translated). Unknown words are kept as they are."""
    text = " ".join(str(text or "").split())
    if not looks_italian(text):
        return text, False
    words = [w for w in tokens(_apply_phrases(text)) if w not in ARTICLES]
    english_words = set(PHRASES.values()) | set(ADJECTIVES.values())
    mapped: list[tuple[str, str]] = []  # (english word, kind)
    for word in words:
        if word in NOUNS:
            mapped.append((NOUNS[word], "noun"))
        elif word in ADJECTIVES:
            mapped.append((ADJECTIVES[word], "adj"))
        elif word in FUNCTION_WORDS:
            mapped.append((FUNCTION_WORDS[word], "fn"))
        elif word in english_words:
            mapped.append((word, "adj"))
        else:
            mapped.append((word, "other"))
    # Italian puts adjectives after the noun, English before it
    result: list[tuple[str, str]] = []
    for word, kind in mapped:
        if kind == "adj" and result and result[-1][1] == "noun":
            result.insert(len(result) - 1, (word, kind))
        else:
            result.append((word, kind))
    english = " ".join(word for word, _ in result).strip()
    if english and english.split()[0] not in {"a", "an", "the"} and not english.startswith(("of", "with")):
        english = ("an " if english[0] in "aeiou" else "a ") + english
    return english or text, True


def build_image_prompt(text: str) -> tuple[str, dict]:
    """The SD-Turbo prompt plus a small report for the debug log."""
    english, translated = to_english(text)
    body = english.rstrip(" ,.")
    low = body.lower()
    for noun, hint in BOXY_HINTS.items():
        if re.search(rf"\b{noun}\b", low):
            if low in (noun, "a " + noun, "an " + noun, "the " + noun):
                body = hint
            elif "box shape" not in low:
                body += ", simple box shape"
            low = body.lower()
            break
    parts = [body]
    if "view" not in low:
        parts.append(VIEW_HINT)
    if "white background" not in low:
        parts.append(IMAGE_SUFFIX)
    if "clean geometry" not in low:
        parts.append(CLEAN_SUFFIX)
    prompt = ", ".join(parts)
    return prompt, {"original": text, "english": english, "translated": translated}
