"""
prueba_integracion.py — checkpoint OFFLINE del Stage A (cableado, sin Telegram).

Prueba la COSTURA que arma bot.py: Orquestador + Memoria + Scheduler reales, unidos
por SchedulerAdapter (schedule->programar) y el nudo de construccion (late-binding de
despachar). Usa un Sender de captura en vez del stub que loguea. DBs en archivos temp.

Corre a mano:  python prueba_integracion.py
"""

import os
import tempfile
import time

import bot   # importa las piezas puras; NO requiere PTB ni token


class SenderCaptura(bot.StubSender):
    """Igual que el stub pero sin log ruidoso; solo acumula en .enviados."""
    def send(self, signal):
        self.enviados.append(signal)


def _tmp(nombre):
    p = os.path.join(tempfile.gettempdir(), nombre)
    if os.path.exists(p):
        os.remove(p)
    return p


fallos = []


# ===========================================================================
# ESCENA 1 — Cableado camino feliz + at-most-once
#   /recuerda +1s -> Orq -> adapter.schedule -> Scheduler.programar (fila pendiente)
#   tick antes de vencer: nada. tras vencer: 1 entrega al Sender. 2do tick: NO re-dispara.
# ===========================================================================
db_mem1, db_sch1 = _tmp("it_mem1.db"), _tmp("it_sch1.db")
snd1 = SenderCaptura()
orq1, sch1, _ = bot.construir_grafo(db_mem1, db_sch1, sender=snd1)

intent = bot.construir_intent_remind(chat_id=12345, segundos=1, texto="comprar pan")
orq1.despachar(intent)   # when!=null -> debe caer en el Scheduler, NO en el Sender

pend = sch1.conn.execute(
    "SELECT COUNT(*) c FROM recordatorios WHERE status='pendiente'").fetchone()["c"]
if pend != 1:
    fallos.append(f"E1: se esperaba 1 fila pendiente tras despachar diferido, hay {pend}")
if len(snd1.enviados) != 0:
    fallos.append("E1: el Sender recibio algo antes de tiempo (diferido mal ruteado)")

sch1.tick()   # aun no vence
if len(snd1.enviados) != 0:
    fallos.append("E1: disparo anticipado (tick antes de fire_at no debe entregar)")

time.sleep(1.1)
sch1.tick()   # ya vencio -> reinyecta -> Orq (when=null) -> Sender
sch1.tick()   # segunda ronda: at-most-once, NO re-dispara
if len(snd1.enviados) != 1:
    fallos.append(f"E1: se esperaba 1 entrega, hubo {len(snd1.enviados)} (at-most-once roto)")
else:
    sig = snd1.enviados[0]
    if sig.get("target") != {"kind": "self", "ref": 12345}:
        fallos.append(f"E1: target mal reinyectado: {sig.get('target')}")
    if sig.get("payload") != "comprar pan":
        fallos.append(f"E1: payload mal reinyectado: {sig.get('payload')!r}")


# ===========================================================================
# ESCENA 2 — Persistencia entre REINICIOS (cero perdida)
#   grafo1 programa +1s y "muere" sin tick. grafo2 (NUEVO Scheduler, MISMA db)
#   levanta y al primer tick dispara el recordatorio que sobrevivio en disco.
# ===========================================================================
db_mem2, db_sch2 = _tmp("it_mem2.db"), _tmp("it_sch2.db")

orq2a, sch2a, _ = bot.construir_grafo(db_mem2, db_sch2, sender=SenderCaptura())
orq2a.despachar(bot.construir_intent_remind(12345, 1, "regar plantas"))
sch2a.conn.close()   # simula caida del proceso: nadie hizo tick todavia

time.sleep(1.1)
snd2 = SenderCaptura()
orq2b, sch2b, _ = bot.construir_grafo(db_mem2, db_sch2, sender=snd2)  # "reinicio", misma db
sch2b.tick()
if len(snd2.enviados) != 1 or snd2.enviados and snd2.enviados[0].get("payload") != "regar plantas":
    fallos.append(f"E2: recordatorio NO sobrevivio al reinicio (entregas={len(snd2.enviados)})")


# ===========================================================================
# ESCENA 3 — El adapter surfacea el rechazo (fecha pasada) y NO crea fila
# ===========================================================================
db_mem3, db_sch3 = _tmp("it_mem3.db"), _tmp("it_sch3.db")
snd3 = SenderCaptura()
orq3, sch3, _ = bot.construir_grafo(db_mem3, db_sch3, sender=snd3)
orq3.despachar(bot.construir_intent_remind(12345, -5, "esto ya pasó"))  # segundos negativos
pend3 = sch3.conn.execute(
    "SELECT COUNT(*) c FROM recordatorios").fetchone()["c"]
if pend3 != 0:
    fallos.append(f"E3: fecha pasada NO debio insertar fila, hay {pend3}")
if len(snd3.enviados) != 0:
    fallos.append("E3: fecha pasada no debio entregar nada")


# ===========================================================================
# ESCENA 4 — Camino INMEDIATO intacto (when=null va directo al Sender, sin Scheduler)
# ===========================================================================
db_mem4, db_sch4 = _tmp("it_mem4.db"), _tmp("it_sch4.db")
snd4 = SenderCaptura()
orq4, sch4, _ = bot.construir_grafo(db_mem4, db_sch4, sender=snd4)
orq4.despachar({
    "action": "remind", "when": None,
    "target": {"kind": "self", "ref": 999},
    "payload": "aviso ya", "raw_text": "aviso ya", "confidence": 1.0,
})
filas4 = sch4.conn.execute("SELECT COUNT(*) c FROM recordatorios").fetchone()["c"]
if len(snd4.enviados) != 1:
    fallos.append(f"E4: inmediato debio ir directo al Sender (entregas={len(snd4.enviados)})")
if filas4 != 0:
    fallos.append(f"E4: inmediato NO debio tocar el Scheduler (filas={filas4})")


# ===========================================================================
# VEREDICTO
# ===========================================================================
if fallos:
    print("FALLOS:")
    for f in fallos:
        print("  -", f)
    raise SystemExit(1)
print("OK — E1 cableado + at-most-once (adapter schedule->programar, reinyeccion): pasó")
print("OK — E2 persistencia entre reinicios (cero perdida en disco): pasó")
print("OK — E3 adapter surfacea rechazo de fecha pasada (sin fila): pasó")
print("OK — E4 camino inmediato intacto (when=null -> Sender, sin Scheduler): pasó")
print("Cableado Stage A verificado.")
