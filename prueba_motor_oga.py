"""
prueba_motor_oga.py — Prueba EN VIVO del motor ASR con un .oga REAL de Telegram.

Esta es LA prueba que zanja si el OGG/Opus de Telegram pasa NATIVO a Gemini
(la doc lista "OGG Vorbis"; Telegram graba "OGG Opus": mismo contenedor y mime,
distinto codec). Aqui se demuestra, no se asume.

Requiere:
  - GEMINI_API_KEY en el entorno (.env cargado; se intenta cargar solo).
  - un archivo .oga real (nota de voz de Telegram).

Uso:
    python prueba_motor_oga.py ruta/al/audio.oga
  (si no pasas ruta, usa 'muestra.oga' en la carpeta actual)

Desenlaces:
  (a) imprime la transcripcion  -> Opus pasa NATIVO. C = cero dependencias.  OK
  (b) error de formato/mime     -> hay que transcodificar (gate propio).
  (c) error de modelo (audio)   -> el lite no come audio: cambia MODELO_ASR a
                                   'gemini-2.5-flash' en transcriber.py y repite
                                   (fallback M2 -> M1).
"""

import asyncio
import sys
import os

# Carga suave del .env (si python-dotenv esta disponible en el proyecto).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from transcriber import motor_gemini, MODELO_ASR


async def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "muestra.oga"
    if not os.path.exists(ruta):
        print(f"[X] No encuentro el archivo: {ruta}")
        print("    Pon una nota de voz .oga de Telegram ahi, o pasa la ruta como argumento.")
        return

    with open(ruta, "rb") as f:
        audio = f.read()

    print(f"Archivo: {ruta}  ({len(audio)} bytes)")
    print(f"Modelo:  {MODELO_ASR}")
    print("Enviando a Gemini como audio/ogg ...\n")

    try:
        texto = await motor_gemini(audio, "audio/ogg")
    except Exception as e:
        print("[X] El motor lanzo un error (crudo, sin disfrazar):")
        print(f"    {type(e).__name__}: {e}")
        print("\n-> Si habla de formato/mime: transcodificar (desenlace b).")
        print("-> Si habla de que el modelo no soporta audio: cambia MODELO_ASR (desenlace c).")
        return

    print("[OK] Transcripcion devuelta:")
    print("-" * 40)
    print(repr(texto))
    print("-" * 40)
    print("\nSi el texto coincide con lo que dijiste -> Opus pasa NATIVO. OK (desenlace a)")


if __name__ == "__main__":
    asyncio.run(main())
