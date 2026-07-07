# interpreter.py — Caja LLM del tramo UPSTREAM (Frontera 6 -> Intent congelado).
#
# Patron C2 (aprobado): la IA SOLO extrae; Python resuelve la fecha y valida.
#   extraer(text, context)         -> Draft      [UNICA pieza estocastica/IO: Gemini]
#   resolver_when(time_expr, ctx)  -> str | None [PURA]  ISO-8601 con offset | None
#   validar(draft, text, context)  -> Intent     [PURA]  ficha congelada / degrada a unknown
#   interpretar(text, context, ex) -> Intent      orquesta las tres
#
# El `Draft` y el `TimeExpr` son INTERNOS: no cruzan ninguna frontera congelada,
# por eso su forma es libre. Lo que cruza a orq.despachar es el Intent v1 congelado:
#   { action, when, target:{kind,ref}, payload, raw_text, confidence }
#
# NOTA DE DEPENDENCIAS: google-genai se importa PEREZOSAMENTE dentro de `extraer`.
# Importar este modulo y usar el nucleo puro (resolver/validar/interpretar+stub)
# NO requiere google-genai instalado -> los tests corren con stdlib sola.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Callable, Optional, Awaitable

# ------------------------------------------------------------------ constantes

CONF_MIN = 0.6  # bajo este umbral -> unknown (el bot repregunta)

ACTIONS = {"remind", "send", "save", "recall", "unknown"}

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_MODEL = "gemini-2.5-flash-lite"  # estable, free tier, alto RPM para extraccion


# ------------------------------------------------------------------ tipo interno

@dataclass
class Draft:
    """Salida cruda del LLM. Interno; no cruza frontera congelada."""
    action: str
    time_expr: dict            # {kind: none|relative|clock|weekday, ...}
    target: dict               # {kind: self|contact, ref: str|None}
    payload: str
    confidence: float


# ------------------------------------------------------------------ helpers puros

def _ahora(context: dict) -> datetime:
    """`context.now` como datetime tz-aware. Si viniera naive, aplica context.tz."""
    now = datetime.fromisoformat(context["now"])
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(context["tz"]))
    return now


def _self_ref(context: dict):
    """chat_id horneado como self.ref (D-CAP-4/5). Tipo = el que emite construir_context;
    debe COINCIDIR con el que el Sender congelado espera (ver nota de cableado)."""
    return context["sender"]["chat_id"]


def _es_futuro(when_iso: str, context: dict) -> bool:
    return datetime.fromisoformat(when_iso) > _ahora(context)


# ------------------------------------------------------------------ resolver_when (PURA)

def resolver_when(time_expr: dict, context: dict) -> Optional[str]:
    """Convierte la expresion temporal estructurada en ISO-8601 absoluto con offset.
    Devuelve None para `none` (accion inmediata). Total: cualquier kind desconocido -> None."""
    now = _ahora(context)
    kind = (time_expr or {}).get("kind", "none")

    if kind == "none":
        return None

    if kind == "relative":
        delta = timedelta(
            days=time_expr.get("days", 0) or 0,
            hours=time_expr.get("hours", 0) or 0,
            minutes=time_expr.get("minutes", 0) or 0,
            seconds=time_expr.get("seconds", 0) or 0,
        )
        return (now + delta).isoformat()

    if kind == "clock":
        hh = int(time_expr["hh"])
        mm = int(time_expr.get("mm", 0) or 0)
        off = int(time_expr.get("day_offset", 0) or 0)
        cand = (now + timedelta(days=off)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if off == 0 and cand <= now:          # solo hoy-o-proxima rueda; manana/pasado NO
            cand += timedelta(days=1)
        return cand.isoformat()

    if kind == "weekday":
        hh = int(time_expr["hh"])
        mm = int(time_expr.get("mm", 0) or 0)
        target_dow = WEEKDAYS[time_expr["weekday"]]
        delta_days = (target_dow - now.weekday()) % 7
        cand = (now + timedelta(days=delta_days)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if cand <= now:                       # ese dia ya paso a esa hora -> proxima semana
            cand += timedelta(days=7)
        return cand.isoformat()

    return None  # kind desconocido: defensivo


# ------------------------------------------------------------------ validar (PURA)

def _unknown(text: str, context: dict, payload: str, confidence: float) -> dict:
    """Intent unknown canonico -> el bot repregunta, no despacha."""
    return {
        "action": "unknown",
        "when": None,
        "target": {"kind": "self", "ref": _self_ref(context)},
        "payload": payload,
        "raw_text": text,
        "confidence": confidence,
    }


def validar(draft: Draft, text: str, context: dict) -> dict:
    """Aplica la tabla del Contrato Intent y estampa lo determinista.
    - raw_text := text SIEMPRE (no viene del LLM).
    - self.ref := context.sender.chat_id para toda accion self (el LLM solo elige la etiqueta).
    - confianza < CONF_MIN o cualquier regla incumplida -> degrada a unknown."""
    action = draft.action if draft.action in ACTIONS else "unknown"
    payload = (draft.payload or "").strip()
    try:
        confidence = float(draft.confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence < CONF_MIN or action == "unknown":
        return _unknown(text, context, payload, confidence)

    # --- target ---
    kind = (draft.target or {}).get("kind")
    if kind == "self":
        target = {"kind": "self", "ref": _self_ref(context)}
    elif kind == "contact":
        ref = ((draft.target or {}).get("ref") or "").strip()
        if not ref:
            return _unknown(text, context, payload, confidence)
        target = {"kind": "contact", "ref": ref}
    else:
        return _unknown(text, context, payload, confidence)

    # --- when ---
    when = resolver_when(draft.time_expr, context)

    # --- reglas por accion (tabla del Contrato Intent) ---
    if action == "remind":
        if when is None or not _es_futuro(when, context) or not payload:
            return _unknown(text, context, payload, confidence)
    elif action == "send":
        if when is not None and not _es_futuro(when, context):
            return _unknown(text, context, payload, confidence)
        if not payload:
            return _unknown(text, context, payload, confidence)
    elif action == "save":
        if when is not None or kind != "self" or not payload:
            return _unknown(text, context, payload, confidence)
    elif action == "recall":
        if when is not None or kind != "self" or not payload:
            return _unknown(text, context, payload, confidence)

    return {
        "action": action,
        "when": when,
        "target": target,
        "payload": payload,
        "raw_text": text,
        "confidence": confidence,
    }


# ------------------------------------------------------------------ extraer (LLM, IO)

# Instruccion de sistema: codifica el enum de acciones, el esquema CERRADO de TimeExpr
# (con la orden explicita de NO calcular fechas), la regla self/contact y la rubrica de
# confianza. Inyecta ahora+zona para anclar "manana / en un rato / el jueves".
_SYSTEM = """Eres un extractor de intenciones para un asistente personal por voz en espanol.
Recibes la transcripcion de una nota de voz y el contexto (ahora, zona horaria, quien manda).
Devuelves SOLO un objeto JSON con la forma del esquema. No expliques nada.

ACCIONES (elige exactamente una):
- remind : el bot me AVISA a MI a una hora futura; yo actuo. payload = mi nota.
- send   : el bot MANDA un mensaje directo a un tercero (ahora o a una hora). payload = texto literal para el otro.
- save   : guardar un dato en mi memoria. Siempre inmediato (sin hora).
- recall : recuperar un dato de mi memoria. Siempre inmediato (sin hora).
- unknown: no se entiende o falta info -> el bot repreguntara.

DESTINATARIO (target.kind):
- "self"    si es para mi (recuerdame, guardame, traeme). target.ref = null (lo pone el sistema).
- "contact" si nombra a un tercero (mandale a mi mama, recuerdale a mi papa). target.ref = el texto crudo del contacto, p.ej. "mi papa". NO inventes numeros ni ids.

TIEMPO (time_expr) -- NO CALCULES FECHAS. Emite solo la expresion estructurada; el sistema calcula la fecha:
- {"kind":"none"}                                  accion inmediata (save, recall, o "mandale ya").
- {"kind":"relative","minutes":M,"hours":H,"days":D,"seconds":S}   "en 20 min", "en 2 horas". Omite los que no apliquen.
- {"kind":"clock","hh":H,"mm":M,"day_offset":O}    hora del reloj. day_offset: 0=hoy-o-proxima, 1=manana, 2=pasado manana. "a las 3"->offset 0; "manana a las 5"->offset 1.
- {"kind":"weekday","weekday":"mon..sun","hh":H,"mm":M}   "el jueves a las 3".
No soportas fechas de calendario ("el 4 de agosto"): si aparece, usa unknown con confidence baja.

CONFIANZA (confidence 0..1): que tan seguro estas de la interpretacion. Si el audio/texto es ambiguo
(p.ej. no queda claro si me recuerdas a mi o le mandas al tercero), baja la confianza por debajo de 0.6.

Responde SOLO el JSON del esquema."""


def _few_shot(context: dict) -> str:
    """Los 5 ejemplos del Contrato Intent reescritos a Draft (con time_expr estructurado)."""
    return (
        'Ejemplos (formato de salida esperado):\n'
        '"a las 12 recuerdame lo del aceite" -> '
        '{"action":"remind","time_expr":{"kind":"clock","hh":12,"mm":0,"day_offset":0},'
        '"target":{"kind":"self","ref":null},"payload":"lo del aceite","confidence":0.95}\n'
        '"mandale a mi mama ya que voy llegando" -> '
        '{"action":"send","time_expr":{"kind":"none"},'
        '"target":{"kind":"contact","ref":"mi mama"},"payload":"ya voy llegando","confidence":0.95}\n'
        '"a las 8 mandale a mi mama que no me espere a cenar" -> '
        '{"action":"send","time_expr":{"kind":"clock","hh":20,"mm":0,"day_offset":0},'
        '"target":{"kind":"contact","ref":"mi mama"},"payload":"que no me espere a cenar","confidence":0.9}\n'
        '"guarda esto: la clave del router es 1234" -> '
        '{"action":"save","time_expr":{"kind":"none"},'
        '"target":{"kind":"self","ref":null},"payload":"la clave del router es 1234","confidence":0.95}\n'
        '"traeme la clave del router" -> '
        '{"action":"recall","time_expr":{"kind":"none"},'
        '"target":{"kind":"self","ref":null},"payload":"clave del router","confidence":0.95}\n'
    )


def _construir_prompt(text: str, context: dict) -> str:
    return (
        f'{_few_shot(context)}\n'
        f'ahora = {context["now"]}\n'
        f'zona = {context["tz"]}\n'
        f'transcripcion = "{text}"\n'
    )


def _coerce_draft(data: dict) -> Draft:
    """Convierte el dict del LLM en Draft, defensivo ante campos faltantes."""
    return Draft(
        action=data.get("action", "unknown"),
        time_expr=data.get("time_expr") or {"kind": "none"},
        target=data.get("target") or {"kind": "self", "ref": None},
        payload=data.get("payload", "") or "",
        confidence=data.get("confidence", 0.0) or 0.0,
    )


# Cliente perezoso (no se crea hasta la primera llamada real a Gemini).
_client = None


def _get_client():
    global _client
    if _client is None:
        import os
        from google import genai  # import perezoso
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _is_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "resourceexhausted" in name or "429" in str(exc)


async def extraer(text: str, context: dict) -> Draft:
    """UNICA pieza estocastica. google-genai async + salida JSON forzada por esquema.
    Reintenta con backoff ante 429. Cualquier fallo -> Draft unknown (el validador repregunta)."""
    import asyncio
    import json
    from google.genai import types  # import perezoso

    # Esquema del Draft para response_schema (forza la forma de salida).
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["remind", "send", "save", "recall", "unknown"]},
            "time_expr": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["none", "relative", "clock", "weekday"]},
                    "days": {"type": "integer"},
                    "hours": {"type": "integer"},
                    "minutes": {"type": "integer"},
                    "seconds": {"type": "integer"},
                    "hh": {"type": "integer"},
                    "mm": {"type": "integer"},
                    "day_offset": {"type": "integer"},
                    "weekday": {"type": "string",
                                "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
                },
                "required": ["kind"],
            },
            "target": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["self", "contact"]},
                    "ref": {"type": "string", "nullable": True},
                },
                "required": ["kind"],
            },
            "payload": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["action", "time_expr", "target", "payload", "confidence"],
    }

    client = _get_client()
    prompt = _construir_prompt(text, context)

    for attempt in range(3):
        try:
            resp = await client.aio.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                ),
            )
            return _coerce_draft(json.loads(resp.text))
        except Exception as exc:                       # noqa: BLE001
            if _is_rate_limit(exc) and attempt < 2:
                await asyncio.sleep(2 ** attempt)      # backoff 1s, 2s
                continue
            return Draft(action="unknown", time_expr={"kind": "none"},
                         target={"kind": "self", "ref": None},
                         payload="", confidence=0.0)


# ------------------------------------------------------------------ interpretar (orquesta)

# El extractor es inyectable: real (`extraer`) en produccion, stub en los tests.
Extractor = Callable[[str, dict], Awaitable[Draft]]


async def interpretar(text: str, context: dict, extractor: Extractor = extraer) -> dict:
    """text + context -> Intent congelado (o unknown). No despacha; eso lo hace bot.py."""
    draft = await extractor(text, context)
    return validar(draft, text, context)
