# prueba_validador.py — QA pura de validar (sin LLM, sin red).

from interpreter import Draft, validar

CTX = {
    "now": "2026-06-15T09:00:00-05:00",   # lunes 09:00
    "tz": "America/Guayaquil",
    "sender": {"chat_id": 1587374864, "name": "JF"},
}
CHAT = 1587374864

fallos = []


def check(nombre, cond):
    print(f"  {'OK ' if cond else 'FALLA'}  {nombre}")
    if not cond:
        fallos.append(nombre)


def D(action, time_expr, target, payload, confidence=0.95):
    return Draft(action=action, time_expr=time_expr, target=target,
                 payload=payload, confidence=confidence)


print("prueba_validador:")

# 1. remind self valido: futuro + payload -> intacto, self.ref estampado = chat_id
i = validar(D("remind", {"kind": "clock", "hh": 12, "day_offset": 0},
              {"kind": "self", "ref": None}, "lo del aceite"), "txt", CTX)
check("remind self valido -> action remind", i["action"] == "remind")
check("remind self estampa chat_id", i["target"] == {"kind": "self", "ref": CHAT})
check("remind pone when futuro", i["when"] == "2026-06-15T12:00:00-05:00")
check("remind raw_text = text original", i["raw_text"] == "txt")

# 2. remind SIN when -> unknown (when obligatorio futuro)
i = validar(D("remind", {"kind": "none"},
              {"kind": "self", "ref": None}, "algo"), "txt", CTX)
check("remind sin when -> unknown", i["action"] == "unknown")

# 3. remind con hora PASADA (imposible aqui porque clock rueda; probamos relative negativo via none)
#    -> usamos un when que el resolver deja en pasado: no hay kind que lo produzca, se cubre en 8.

# 4. send contact ahora -> valido, ref crudo conservado
i = validar(D("send", {"kind": "none"},
              {"kind": "contact", "ref": "mi mama"}, "ya voy llegando"), "txt", CTX)
check("send contact ahora -> send", i["action"] == "send" and i["when"] is None)
check("send conserva ref crudo 'mi mama'", i["target"] == {"kind": "contact", "ref": "mi mama"})

# 5. send contact futuro -> valido con when
i = validar(D("send", {"kind": "clock", "hh": 20, "day_offset": 0},
              {"kind": "contact", "ref": "mi mama"}, "que no me espere"), "txt", CTX)
check("send contact futuro -> when 20:00", i["action"] == "send" and i["when"] == "2026-06-15T20:00:00-05:00")

# 6. save self ahora -> valido
i = validar(D("save", {"kind": "none"},
              {"kind": "self", "ref": None}, "la clave es 1234"), "txt", CTX)
check("save self -> save, when None", i["action"] == "save" and i["when"] is None)

# 7. save CON hora -> unknown (save siempre inmediato)
i = validar(D("save", {"kind": "clock", "hh": 12, "day_offset": 0},
              {"kind": "self", "ref": None}, "algo"), "txt", CTX)
check("save con hora -> unknown", i["action"] == "unknown")

# 8. save con target contact -> unknown (save es self)
i = validar(D("save", {"kind": "none"},
              {"kind": "contact", "ref": "mi mama"}, "algo"), "txt", CTX)
check("save contact -> unknown", i["action"] == "unknown")

# 9. recall self -> valido
i = validar(D("recall", {"kind": "none"},
              {"kind": "self", "ref": None}, "clave del router"), "txt", CTX)
check("recall self -> recall", i["action"] == "recall" and i["when"] is None)

# 10. payload vacio en remind -> unknown
i = validar(D("remind", {"kind": "clock", "hh": 12, "day_offset": 0},
              {"kind": "self", "ref": None}, "   "), "txt", CTX)
check("remind payload vacio -> unknown", i["action"] == "unknown")

# 11. confianza baja -> unknown (aunque todo lo demas este bien)
i = validar(D("remind", {"kind": "clock", "hh": 12, "day_offset": 0},
              {"kind": "self", "ref": None}, "algo", confidence=0.4), "txt", CTX)
check("confianza 0.4 -> unknown", i["action"] == "unknown")
check("unknown tambien estampa self.ref", i["target"] == {"kind": "self", "ref": CHAT})

# 12. contact con ref vacio -> unknown
i = validar(D("send", {"kind": "none"},
              {"kind": "contact", "ref": "  "}, "hola"), "txt", CTX)
check("contact ref vacio -> unknown", i["action"] == "unknown")

# 13. action fuera del enum -> unknown
i = validar(D("borrar", {"kind": "none"},
              {"kind": "self", "ref": None}, "algo"), "txt", CTX)
check("action no-enum -> unknown", i["action"] == "unknown")

# 14. la ficha siempre trae las 6 llaves del contrato
i = validar(D("recall", {"kind": "none"}, {"kind": "self", "ref": None}, "x"), "txt", CTX)
check("ficha con 6 llaves congeladas",
      set(i.keys()) == {"action", "when", "target", "payload", "raw_text", "confidence"})

print(f"\nRESULTADO validador: {'TODOS VERDES' if not fallos else 'FALLOS: ' + str(fallos)}")
raise SystemExit(1 if fallos else 0)
