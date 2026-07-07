"""
prueba_transcriber.py — Verificacion OFFLINE de la caja U2 (sin Gemini).

Valida el contrato de `transcribir` con un motor STUB:
  - passthrough del context intacto (mismo contenido Y misma identidad).
  - forma de salida F6 = {"text", "context"} exacta.
No gasta ni una llamada a la API. Corre sin GEMINI_API_KEY (import perezoso).

Uso:
    python prueba_transcriber.py
"""

import asyncio

from transcriber import transcribir


async def _stub_motor(audio, mime):
    # Motor falso: ignora el audio, devuelve texto fijo. Prueba la orquestacion,
    # no el oido. El oido real se prueba en prueba_motor_oga.py.
    return "hola esto es una prueba"


def _ok(cond, nombre):
    print(("PASS" if cond else "FALL") + " - " + nombre)
    return 1 if cond else 0


async def main():
    context = {
        "now": "2026-07-07T09:00:00-05:00",
        "tz": "America/Guayaquil",
        "sender": {"chat_id": 12345, "name": "JF"},
    }
    audio = b"OggS-falso-no-se-mira"
    out = await transcribir(audio, "audio/ogg", 7, context, motor=_stub_motor)

    total = 0
    ok = 0
    total += 1; ok += _ok(out["text"] == "hola esto es una prueba", "texto viene del motor")
    total += 1; ok += _ok(set(out.keys()) == {"text", "context"}, "salida F6 = solo text+context")
    total += 1; ok += _ok(out["context"] == context, "context igual en contenido (passthrough)")
    total += 1; ok += _ok(out["context"] is context, "context es el MISMO objeto (no se copio/abrio)")
    total += 1; ok += _ok(isinstance(out["text"], str), "text es str")

    print(f"\n{ok}/{total} verdes")


if __name__ == "__main__":
    asyncio.run(main())
