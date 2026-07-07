"""
transcriber.py — Caja U2: Transcripcion (Frontera 5 -> Frontera 6).

Contrato Captura (CONGELADO v1 + D-CAP-1/2/5):
  ENTRA (F5):  audio: bytes, mime: str, duration_s: int, context: dict (OPACO)
  SALE  (F6):  {"text": str, "context": dict}   <- mismo context, passthrough intacto

Reglas del contrato honradas aqui:
  - U2 es AGNOSTICA a Telegram: solo ve bytes + mime, no sabe de donde vino.
  - PASSTHROUGH: nunca abre `context`, lo reenvia identico (D-CAP-1).
  - v1 devuelve SOLO `text` (D-CAP-2: confidence_asr es extension futura).
  - El motor ASR vive tras un SEAM (inyectable): real | stub.

Patron heredado de U1 (interpreter.py):
  - Nucleo PURO importable/testeable sin el SDK (import perezoso de genai).
  - La unica pieza estocastica/IO es `motor_gemini`.
"""

from __future__ import annotations

import os
import asyncio

# Modelo por defecto (M2). Cambiar este STRING es el UNICO cambio para migrar
# a otro modelo (p.ej. "gemini-2.5-flash" si el lite no acepta audio). El seam
# hace que el resto de la caja no se entere.
MODELO_ASR = "gemini-2.5-flash-lite"

# Instruccion de transcripcion. Prohibe editorializar y traducir: F6 debe
# recibir texto limpio, en el idioma original, sin preambulos.
_PROMPT_TRANSCRIPCION = (
    "Transcribe textualmente el audio en su idioma original. "
    "Devuelve UNICAMENTE la transcripcion literal, sin comillas, sin "
    "preambulos, sin comentarios y sin traducir. Si el audio esta vacio o es "
    "ininteligible, devuelve una cadena vacia."
)

# Cliente cacheado a nivel modulo (se crea UNA sola vez, perezosamente).
_cliente = None


def _get_cliente():
    """Crea (una vez) el cliente genai. Import PEREZOSO: el nucleo puro se
    importa sin el SDK; solo el camino real lo necesita."""
    global _cliente
    if _cliente is None:
        from google import genai  # import perezoso
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Falta GEMINI_API_KEY en el entorno (.env). El motor real la exige."
            )
        _cliente = genai.Client(api_key=api_key)
    return _cliente


async def motor_gemini(audio: bytes, mime: str, *, reintentos: int = 3) -> str:
    """UNICA pieza estocastica/IO. Manda el audio a Gemini y devuelve el texto.

    - Usa el carril async (client.aio) como U1.
    - Reintento con backoff exponencial ante 429 (RESOURCE_EXHAUSTED).
    - Propaga cualquier otro error CRUDO (no lo disfraza): el manejo elegante
      vive en el cableado del bot (U3), no aqui.
    """
    from google.genai import types, errors  # import perezoso

    cliente = _get_cliente()
    parte_audio = types.Part.from_bytes(data=audio, mime_type=mime)
    config = types.GenerateContentConfig(temperature=0.0)

    espera = 1.0
    for intento in range(reintentos):
        try:
            resp = await cliente.aio.models.generate_content(
                model=MODELO_ASR,
                contents=[_PROMPT_TRANSCRIPCION, parte_audio],
                config=config,
            )
            return (resp.text or "").strip()
        except errors.APIError as e:
            # 429 = cuota/rate. Reintenta con backoff; el resto se propaga.
            if getattr(e, "code", None) == 429 and intento < reintentos - 1:
                await asyncio.sleep(espera)
                espera *= 2
                continue
            raise

    raise RuntimeError("motor_gemini agoto reintentos sin respuesta")


async def transcribir(
    audio: bytes,
    mime: str,
    duration_s: int,
    context: dict,
    *,
    motor=motor_gemini,
) -> dict:
    """Caja U2. Orquesta: pide la transcripcion al motor (inyectable) y arma la
    salida F6. El `context` se PASA DE LARGO intacto (passthrough, D-CAP-1);
    U2 nunca lo abre.

    `duration_s` se acepta por contrato; en v1 NO se usa (seam para una guarda
    de duracion futura). No se inventa logica sobre el.
    """
    text = await motor(audio, mime)
    return {"text": text, "context": context}
