"""Deterministic Italian commands for the GEV map and its embedded Chrome panel."""

from __future__ import annotations

import re
import unicodedata

EUROPEAN_COUNTRIES: tuple[tuple[str, float, float], ...] = (
    ("Albania", 41.3275, 19.8187),
    ("Andorra", 42.5063, 1.5218),
    ("Armenia", 40.1792, 44.4991),
    ("Austria", 48.2082, 16.3738),
    ("Azerbaigian", 40.4093, 49.8671),
    ("Bielorussia", 53.9006, 27.5590),
    ("Belgio", 50.8503, 4.3517),
    ("Bosnia ed Erzegovina", 43.8563, 18.4131),
    ("Bulgaria", 42.6977, 23.3219),
    ("Cipro", 35.1856, 33.3823),
    ("Cechia", 50.0755, 14.4378),
    ("Croazia", 45.8150, 15.9819),
    ("Danimarca", 55.6761, 12.5683),
    ("Estonia", 59.4370, 24.7536),
    ("Finlandia", 60.1699, 24.9384),
    ("Francia", 48.8566, 2.3522),
    ("Georgia", 41.7151, 44.8271),
    ("Germania", 52.5200, 13.4050),
    ("Grecia", 37.9838, 23.7275),
    ("Ungheria", 47.4979, 19.0402),
    ("Islanda", 64.1466, -21.9426),
    ("Irlanda", 53.3498, -6.2603),
    ("Italia", 41.9028, 12.4964),
    ("Kosovo", 42.6629, 21.1655),
    ("Lettonia", 56.9496, 24.1052),
    ("Liechtenstein", 47.1410, 9.5209),
    ("Lituania", 54.6872, 25.2797),
    ("Lussemburgo", 49.6116, 6.1319),
    ("Malta", 35.8992, 14.5141),
    ("Moldavia", 47.0105, 28.8638),
    ("Monaco", 43.7384, 7.4246),
    ("Montenegro", 42.4304, 19.2594),
    ("Paesi Bassi", 52.3676, 4.9041),
    ("Macedonia del Nord", 41.9981, 21.4254),
    ("Norvegia", 59.9139, 10.7522),
    ("Polonia", 52.2297, 21.0122),
    ("Portogallo", 38.7223, -9.1393),
    ("Regno Unito", 51.5072, -0.1276),
    ("Romania", 44.4268, 26.1025),
    ("Russia", 55.7558, 37.6173),
    ("San Marino", 43.9424, 12.4578),
    ("Serbia", 44.7866, 20.4489),
    ("Slovacchia", 48.1486, 17.1077),
    ("Slovenia", 46.0569, 14.5058),
    ("Spagna", 40.4168, -3.7038),
    ("Svezia", 59.3293, 18.0686),
    ("Svizzera", 46.9480, 7.4474),
    ("Turchia", 39.9334, 32.8597),
    ("Ucraina", 50.4501, 30.5234),
    ("Città del Vaticano", 41.9029, 12.4534),
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def classify_gev_command(text: str) -> str | None:
    """Return a known command name without routing ordinary chat to the map."""
    if not isinstance(text, str):
        return None
    command = re.sub(r"\s+", " ", _normalize(text)).strip(" \t\r\n.,!?;:")

    if re.fullmatch(
        r"(?:(?:elenca|mostra|dimmi)\s+(?:i\s+)?)?comandi(?:\s+gev)?",
        command,
    ):
        return "help"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:apri|mostra|visualizza|avvia|lancia|open|vai(?:\s+(?:a|su))?)\s+"
        r"(?:(?:la|il)\s+)?(?:app\s+)?"
        r"(?:god[' ]?s\s+eye\s+view|god\s+eye\s+view|gods\s+eye\s+view|"
        r"gev|mappa(?:\s+gev)?)",
        command,
    ):
        return "open_gev"
    if re.fullmatch(
        r"(?:elenca|lista|mostra|quali sono)\s+(?:tutti\s+)?(?:i\s+)?"
        r"paesi(?:\s+(?:europei|d[' ]?europa|in europa))?",
        command,
    ):
        return "list_countries"
    if re.fullmatch(r"(?:ferma|interrompi|stop)(?:\s+(?:il\s+)?tour(?:\s+(?:d[' ]?europa|europa))?)?", command):
        return "tour_stop"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis)\s+)?(?:(?:fai|avvia|inizia|lancia|fammi)\s+)?"
        r"(?:un\s+)?(?:tour|giro)\s+(?:d[' ]?europa|europa|eropa|dei paesi europei|"
        r"dei paesi d[' ]europa)",
        command,
    ):
        return "tour_start"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:(?:zoom in|ingrandisci|aumenta zoom)"
        r"(?:\s+(?:(?:su|di)\s+)?(?:chrome|youtube|browser))?|"
        r"zoom avanti\s+(?:(?:su|di)\s+)?(?:chrome|youtube|browser))|"
        r"(?:chrome|youtube|browser)\s+zoom\s+(?:avanti|in)",
        command,
    ):
        return "chrome_zoom_in"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:(?:zoom out|rimpicciolisci|riduci zoom)"
        r"(?:\s+(?:(?:su|di)\s+)?(?:chrome|youtube|browser))?|"
        r"zoom indietro\s+(?:(?:su|di)\s+)?(?:chrome|youtube|browser))|"
        r"(?:chrome|youtube|browser)\s+zoom\s+(?:indietro|out)",
        command,
    ):
        return "chrome_zoom_out"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:reset|azzera|ripristina)(?:\s+(?:lo|il))?\s+zoom"
        r"(?:\s+(?:(?:su|di)\s+)?(?:chrome|youtube|browser))?|"
        r"(?:chrome|youtube|browser)\s+zoom\s+(?:normale|reset)",
        command,
    ):
        return "chrome_zoom_reset"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:cosa\s+(?:c'e|ce)\s+(?:sullo schermo|a schermo)|"
        r"cosa vedi(?:\s+(?:sullo schermo|a schermo))?|"
        r"analizza(?:\s+questa)?\s+(?:schermata|immagine)|"
        r"analizza\s+(?:la\s+)?finestra\s+(?:attiva|in primo piano)|"
        r"leggi(?:\s+questa|\s+la)?\s+pagina|"
        r"usa google lens|google lens|"
        r"amplifica(?:\s+(?:la\s+)?schermata))",
        command,
    ):
        return "screen_analysis"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"attiva(?:\s+la)?\s+lente(?:\s+di\s+ingrandimento)?",
        command,
    ):
        return "screen_magnifier_on"
    if re.fullmatch(
        r"(?:(?:per favore|jarvis|iris)[,]?\s+)?"
        r"(?:disattiva|chiudi|spegni)(?:\s+la)?\s+lente"
        r"(?:\s+di\s+ingrandimento)?",
        command,
    ):
        return "screen_magnifier_off"
    if re.fullmatch(
        r"(?:zoom avanti|ingrandisci(?: la)? mappa|avvicina(?: la)? mappa)",
        command,
    ):
        return "zoom_in"
    if re.fullmatch(
        r"(?:zoom indietro|riduci(?: lo)? zoom(?: della)? mappa|"
        r"allontana(?: la)? mappa)",
        command,
    ):
        return "zoom_out"
    if re.fullmatch(
        r"(?:espandi|ingrandisci|amplia|allarga) chrome|"
        r"(?:chrome|youtube) a schermo intero",
        command,
    ):
        return "chrome_expand"
    if re.fullmatch(
        r"(?:riduci|ripristina) chrome|"
        r"(?:esci da|chiudi) schermo intero|"
        r"(?:mostra|ripristina) la chat",
        command,
    ):
        return "chrome_restore"
    return None
