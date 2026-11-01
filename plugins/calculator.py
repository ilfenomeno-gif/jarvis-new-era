"""
JARVIS plugin: calcolatrice matematica sicura.

Valuta espressioni aritmetiche (anche con funzioni comuni come sqrt, sin, cos,
log, potenze, percentuali) senza usare eval() sull'input dell'utente: l'albero
sintattico viene analizzato con il modulo `ast` e solo nodi/operatori/funzioni
in whitelist vengono eseguiti. Qualsiasi altro contenuto (import, attributi,
chiamate a funzioni non consentite, ecc.) viene rifiutato prima dell'esecuzione.
"""

import ast
import math
import operator

PLUGIN = {
    "name": "calculator",
    "description": (
        "Esegue calcoli matematici e conversioni numeriche a partire da una "
        "espressione testuale, ad esempio '12 * (3 + 4)', 'sqrt(144)', "
        "'15% di 200' o '2^10'. Usare questo strumento per qualsiasi domanda "
        "aritmetica o calcolo numerico pronunciato dall'utente. NON usare "
        "questo strumento per conversioni di valuta in tempo reale (nessun "
        "tasso di cambio integrato) o per domande generali non numeriche."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "expression": {
                "type": "STRING",
                "description": "L'espressione matematica da calcolare, come scritta o dettata dall'utente.",
            },
        },
        "required": ["expression"],
    },
}

# Operatori consentiti
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
# Funzioni e costanti consentite
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "min": min,
    "max": max,
    "factorial": math.factorial,
}
_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

_MAX_RESULT_MAGNITUDE = 1e18  # evita di produrre numeri assurdi da input maligni (es. 9**9**9)


def _normalize(expression: str) -> str:
    """Normalizza notazioni comuni (^, %, virgola come separatore migliaia, italiano)."""
    text = expression.strip().lower()
    text = text.replace(",", ".")
    text = text.replace("^", "**")
    text = text.replace("x", "*") if " x " in f" {text} " else text
    text = text.replace("di ", "* ")   # "15% di 200" -> "15% * 200"
    text = text.replace("%", "/100")
    return text


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Costante non numerica non consentita.")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise ValueError(f"Operatore non consentito: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if op_type is ast.Pow and (abs(left) > 10_000 or abs(right) > 1_000):
            raise ValueError("Esponente troppo grande.")
        return _BIN_OPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ValueError(f"Operatore unario non consentito: {op_type.__name__}")
        return _UNARY_OPS[op_type](_safe_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("Funzione non consentita.")
        if node.keywords:
            raise ValueError("Argomenti keyword non consentiti.")
        args = [_safe_eval(a) for a in node.args]
        return _FUNCTIONS[node.func.id](*args)
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"Simbolo non riconosciuto: {node.id}")
    raise ValueError(f"Espressione non consentita: {type(node).__name__}")


def _format_result(value) -> str:
    if isinstance(value, float):
        if abs(value) > _MAX_RESULT_MAGNITUDE:
            raise OverflowError("Il risultato e troppo grande.")
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


def run(parameters: dict, player=None, session_memory=None) -> str:
    raw_expression = str(parameters.get("expression", "")).strip()
    if not raw_expression:
        return "Sir, non ho ricevuto nessuna espressione da calcolare."

    try:
        normalized = _normalize(raw_expression)
        tree = ast.parse(normalized, mode="eval")
        result = _safe_eval(tree)
        formatted = _format_result(result)
        result_text = f"{raw_expression} = {formatted}"
    except ZeroDivisionError:
        return "Sir, quel calcolo comporta una divisione per zero."
    except (SyntaxError, ValueError, TypeError, OverflowError) as e:
        return f"Sir, non sono riuscito a calcolare '{raw_expression}': {e}"
    except Exception as e:
        return f"Sir, la calcolatrice ha riscontrato un errore imprevisto: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {result_text}")
        except Exception:
            pass
    return result_text
