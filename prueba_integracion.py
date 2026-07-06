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
# ESCENA 5 — Sender real (Stage B): resolucion por kind + puente create_task
#   Doble de Application: create_task captura la corrutina (no la manda a Telegram).
# ===========================================================================
import sender as sender_mod


class FakeBot:
    def __init__(self):
        self.llamadas = []

    async def send_message(self, chat_id, text):
        self.llamadas.append((chat_id, text))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.tasks = []

    def create_task(self, coro):
        self.tasks.append(coro)   # captura; NO lo corre (evita necesitar loop real)


fapp = FakeApp()
snd_real = sender_mod.Sender(fapp)

# 5a: kind:self -> resuelve al chat_id con prefijo, y encola 1 corrutina
plan_self = snd_real._resolver({"target": {"kind": "self", "ref": 777}, "payload": "comprar pan"})
if not (plan_self["entregar"] and plan_self["chat_id"] == 777
        and plan_self["texto"] == "⏰ Recordatorio: comprar pan"):
    fallos.append(f"E5a: _resolver(self) mal: {plan_self}")
snd_real.send({"target": {"kind": "self", "ref": 777}, "payload": "comprar pan"})
if len(fapp.tasks) != 1:
    fallos.append(f"E5a: self debio encolar 1 corrutina, encoló {len(fapp.tasks)}")

# 5b: kind:contact -> NO entrega (B1), NO encola
plan_contact = snd_real._resolver({"target": {"kind": "contact", "ref": "mi papá"}, "payload": "x"})
if plan_contact["entregar"]:
    fallos.append("E5b: contact NO debia entregar en B1")
tasks_antes = len(fapp.tasks)
snd_real.send({"target": {"kind": "contact", "ref": "mi papá"}, "payload": "x"})
if len(fapp.tasks) != tasks_antes:
    fallos.append("E5b: contact no debio encolar nada")

# 5c: cadena completa tick -> despachar -> Sender real (con FakeApp)
db_mem5, db_sch5 = _tmp("it_mem5.db"), _tmp("it_sch5.db")
fapp2 = FakeApp()
orq5, sch5, _ = bot.construir_grafo(db_mem5, db_sch5, sender=sender_mod.Sender(fapp2))
orq5.despachar(bot.construir_intent_remind(chat_id=555, segundos=1, texto="regar"))
time.sleep(1.1)
sch5.tick()
if len(fapp2.tasks) != 1:
    fallos.append(f"E5c: la cadena tick->Sender debio encolar 1, encoló {len(fapp2.tasks)}")

# limpieza: cerrar corrutinas capturadas para no dejar 'never awaited'
for _t in fapp.tasks + fapp2.tasks:
    _t.close()


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
print("OK — E5 Sender real: self resuelve+prefijo+encola, contact no entrega (B1), cadena tick->Sender: pasó")
print("Cableado Stage A + Sender Stage B verificado.")
