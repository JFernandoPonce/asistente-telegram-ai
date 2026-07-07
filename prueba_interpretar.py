# prueba_interpretar.py — QA del nucleo completo interpretar() con StubExtractor.
# Prueba la cadena extraer->validar SIN Gemini: el stub devuelve el Draft canned
# que el LLM deberia producir para cada frase del Contrato Intent.

import asyncio
from interpreter import Draft, interpretar

CTX = {
    "now": "2026-06-15T09:00:00-05:00",   # lunes 09:00
    "tz": "America/Guayaquil",
    "sender": {"chat_id": 1587374864, "name": "JF"},
}
CHAT = 1587374864

# Mapa frase -> Draft canned (lo que se espera que el LLM extraiga).
DRAFTS = {
    "a las 12 recuerdame lo del aceite":
        Draft("remind", {"kind": "clock", "hh": 12, "mm": 0, "day_offset": 0},
              {"kind": "self", "ref": None}, "lo del aceite", 0.95),
    "mandale a mi mama ya que voy llegando":
        Draft("send", {"kind": "none"},
              {"kind": "contact", "ref": "mi mama"}, "ya voy llegando", 0.95),
    "a las 8 mandale a mi mama que no me espere a cenar":
        Draft("send", {"kind": "clock", "hh": 20, "mm": 0, "day_offset": 0},
              {"kind": "contact", "ref": "mi mama"}, "que no me espere a cenar", 0.9),
    "guarda esto: la clave del router es 1234":
        Draft("save", {"kind": "none"},
              {"kind": "self", "ref": None}, "la clave del router es 1234", 0.95),
    "traeme la clave del router":
        Draft("recall", {"kind": "none"},
              {"kind": "self", "ref": None}, "clave del router", 0.95),
    # frase ambigua -> el LLM baja confianza -> unknown (repregunta)
    "recuerdale a mi papa lo del aceite":
        Draft("send", {"kind": "clock", "hh": 12, "mm": 0, "day_offset": 0},
              {"kind": "contact", "ref": "mi papa"}, "lo del aceite", 0.4),
}


async def stub_extractor(text, context):
    return DRAFTS[text]


fallos = []


def check(nombre, cond):
    print(f"  {'OK ' if cond else 'FALLA'}  {nombre}")
    if not cond:
        fallos.append(nombre)


async def run():
    print("prueba_interpretar (nucleo con stub):")

    i = await interpretar("a las 12 recuerdame lo del aceite", CTX, stub_extractor)
    check("remind -> self+chat_id, hoy 12:00, payload",
          i["action"] == "remind" and i["target"] == {"kind": "self", "ref": CHAT}
          and i["when"] == "2026-06-15T12:00:00-05:00" and i["payload"] == "lo del aceite"
          and i["raw_text"] == "a las 12 recuerdame lo del aceite")

    i = await interpretar("mandale a mi mama ya que voy llegando", CTX, stub_extractor)
    check("send ahora -> contact 'mi mama', when None",
          i["action"] == "send" and i["target"] == {"kind": "contact", "ref": "mi mama"}
          and i["when"] is None and i["payload"] == "ya voy llegando")

    i = await interpretar("a las 8 mandale a mi mama que no me espere a cenar", CTX, stub_extractor)
    check("send futuro -> contact, when 20:00",
          i["action"] == "send" and i["target"]["kind"] == "contact"
          and i["when"] == "2026-06-15T20:00:00-05:00")

    i = await interpretar("guarda esto: la clave del router es 1234", CTX, stub_extractor)
    check("save -> self, when None, payload completo",
          i["action"] == "save" and i["target"] == {"kind": "self", "ref": CHAT}
          and i["when"] is None and i["payload"] == "la clave del router es 1234")

    i = await interpretar("traeme la clave del router", CTX, stub_extractor)
    check("recall -> self, consulta como payload",
          i["action"] == "recall" and i["payload"] == "clave del router" and i["when"] is None)

    i = await interpretar("recuerdale a mi papa lo del aceite", CTX, stub_extractor)
    check("ambigua (conf 0.4) -> unknown (repregunta)", i["action"] == "unknown")

    print(f"\nRESULTADO interpretar: {'TODOS VERDES' if not fallos else 'FALLOS: ' + str(fallos)}")
    return 1 if fallos else 0


raise SystemExit(asyncio.run(run()))
