# prueba_resolver.py — QA pura de resolver_when (sin LLM, sin red).
# now fijo = America/Guayaquil (offset fijo -05:00, sin DST).

from datetime import datetime
from interpreter import resolver_when

CTX = {
    "now": "2026-06-15T09:00:00-05:00",   # 2026-06-15 = LUNES 09:00
    "tz": "America/Guayaquil",
    "sender": {"chat_id": 1587374864, "name": "JF"},
}

fallos = []


def check(nombre, cond):
    print(f"  {'OK ' if cond else 'FALLA'}  {nombre}")
    if not cond:
        fallos.append(nombre)


def iso(s):
    return datetime.fromisoformat(s)


print("prueba_resolver:")

# 1. none -> None
check("none -> None", resolver_when({"kind": "none"}, CTX) is None)

# 2. relative 20 min -> +20min, mismo offset
w = resolver_when({"kind": "relative", "minutes": 20}, CTX)
check("relative 20min = 09:20", iso(w) == iso("2026-06-15T09:20:00-05:00"))
check("relative conserva offset -05:00", w.endswith("-05:00"))

# 3. relative 2h 30m
w = resolver_when({"kind": "relative", "hours": 2, "minutes": 30}, CTX)
check("relative 2h30m = 11:30", iso(w) == iso("2026-06-15T11:30:00-05:00"))

# 4. clock a las 12 (hoy, aun no pasa) -> hoy 12:00
w = resolver_when({"kind": "clock", "hh": 12, "mm": 0, "day_offset": 0}, CTX)
check("clock 12:00 hoy (futuro) = hoy 12:00", iso(w) == iso("2026-06-15T12:00:00-05:00"))

# 5. clock a las 8 (ya paso, son las 9) -> MANANA 08:00 (rueda)
w = resolver_when({"kind": "clock", "hh": 8, "mm": 0, "day_offset": 0}, CTX)
check("clock 08:00 ya paso -> manana 08:00", iso(w) == iso("2026-06-16T08:00:00-05:00"))

# 6. "manana a las 5" -> day_offset 1, 05:00 del dia siguiente (NO rueda aunque 5<9)
w = resolver_when({"kind": "clock", "hh": 5, "mm": 0, "day_offset": 1}, CTX)
check("clock manana 05:00 = 2026-06-16 05:00", iso(w) == iso("2026-06-16T05:00:00-05:00"))

# 7. "pasado manana a las 8" -> day_offset 2
w = resolver_when({"kind": "clock", "hh": 8, "mm": 0, "day_offset": 2}, CTX)
check("clock pasado 08:00 = 2026-06-17 08:00", iso(w) == iso("2026-06-17T08:00:00-05:00"))

# 8. weekday jueves a las 15 (hoy lunes) -> jueves 2026-06-18 15:00
w = resolver_when({"kind": "weekday", "weekday": "thu", "hh": 15, "mm": 0}, CTX)
check("weekday jueves 15:00 = 2026-06-18 15:00", iso(w) == iso("2026-06-18T15:00:00-05:00"))

# 9. weekday LUNES a las 15 (hoy lunes, 15>9 futuro) -> HOY 15:00 (delta 0, futuro)
w = resolver_when({"kind": "weekday", "weekday": "mon", "hh": 15, "mm": 0}, CTX)
check("weekday lunes 15:00 (hoy futuro) = hoy 15:00", iso(w) == iso("2026-06-15T15:00:00-05:00"))

# 10. weekday LUNES a las 8 (hoy lunes, 8<9 ya paso) -> PROXIMO lunes +7d
w = resolver_when({"kind": "weekday", "weekday": "mon", "hh": 8, "mm": 0}, CTX)
check("weekday lunes 08:00 ya paso -> +7d 2026-06-22 08:00", iso(w) == iso("2026-06-22T08:00:00-05:00"))

# 11. kind desconocido -> None defensivo
check("kind raro -> None", resolver_when({"kind": "zzz"}, CTX) is None)

print(f"\nRESULTADO resolver: {'TODOS VERDES' if not fallos else 'FALLOS: ' + str(fallos)}")
raise SystemExit(1 if fallos else 0)
