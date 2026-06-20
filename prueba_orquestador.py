"""
Prueba del Orquestador con CAJAS DE CARTON.

Las cajas de carton no hacen el trabajo real: solo ANOTAN con que se las llamo.
Asi podemos verificar que el Orquestador repartio cada nota de voz al lugar correcto,
SIN haber construido todavia el Scheduler, la Memoria ni el Sender de verdad.

Analogia: abrimos la llave del cuarto de huespedes y confirmamos que el agua
llega ahi y no a la cocina. Despues ya pondremos la grmiferia bonita.
"""

from orquestador import Orquestador


# ----------------------------------------------------------------------------
# CAJAS DE CARTON (dobles de prueba)
# ----------------------------------------------------------------------------
class CartonScheduler:
    def __init__(self):
        self.jobs = []
    def schedule(self, job):
        self.jobs.append(job)


class CartonMemoria:
    def __init__(self):
        self.guardado = []                 # saves recibidos
    def handle(self, message):
        if message["op"] == "save":
            self.guardado.append(message)
            return {"ok": True}
        if message["op"] == "recall":
            q = message["query"].lower()    # busqueda boba: ¿algo guardado contiene la consulta?
            for m in self.guardado:
                if q in m["content"].lower():
                    return {"result": m["content"]}
            return {"result": "(no encontré nada)"}
        return {"ok": False}


class CartonSender:
    def __init__(self):
        self.enviado = []
    def send(self, signal):
        self.enviado.append(signal)


def reloj_fijo():
    return "2026-06-19T10:00:00-05:00"      # reloj congelado -> prueba determinista


# ----------------------------------------------------------------------------
# Montaje del sistema (con cartones)
# ----------------------------------------------------------------------------
sch, mem, snd = CartonScheduler(), CartonMemoria(), CartonSender()
orq = Orquestador(scheduler=sch, memoria=mem, sender=snd, clock=reloj_fijo)


def linea(titulo):
    print("\n" + "-" * 70 + f"\n{titulo}")


# ============================================================================
# EL DIA DE JF: una a una, las notas de voz entran al Orquestador.
# ============================================================================

# 1) "mándale a mi mamá ya que voy llegando"  -> send AHORA
linea("1) SEND inmediato  ->  debe ir al Sender, hacia 'mi mamá'")
orq.despachar({
    "action": "send", "when": None,
    "target": {"kind": "contact", "ref": "mi mamá"},
    "payload": "ya voy llegando",
    "raw_text": "mándale a mi mamá ya que voy llegando", "confidence": 0.9,
})
assert len(snd.enviado) == 1
assert snd.enviado[-1] == {"target": {"kind": "contact", "ref": "mi mamá"},
                           "payload": "ya voy llegando"}
print("   Sender recibio:", snd.enviado[-1])

# 2) "guarda esto: la clave del router es 1234"  -> save
linea("2) SAVE  ->  debe ir a Memoria; NO debe avisar al usuario (silencioso)")
sender_antes = len(snd.enviado)
orq.despachar({
    "action": "save", "when": None,
    "target": {"kind": "self", "ref": "123456789"},
    "payload": "la clave del router es 1234",
    "raw_text": "guarda esto: la clave del router es 1234", "confidence": 0.97,
})
assert len(mem.guardado) == 1
assert mem.guardado[-1]["content"] == "la clave del router es 1234"
assert mem.guardado[-1]["source_text"] == "guarda esto: la clave del router es 1234"
assert mem.guardado[-1]["saved_at"] == "2026-06-19T10:00:00-05:00"
assert len(snd.enviado) == sender_antes        # <- save NO mando nada al Sender
print("   Memoria guardo:", mem.guardado[-1])
print("   Sender NO fue llamado (correcto: save es silencioso en v1)")

# 3) "tráeme la clave del router"  -> recall (REBOTA: Memoria -> Sender)
linea("3) RECALL  ->  Memoria busca y el resultado REBOTA al usuario via Sender")
orq.despachar({
    "action": "recall", "when": None,
    "target": {"kind": "self", "ref": "123456789"},
    "payload": "clave del router",
    "raw_text": "tráeme la clave del router", "confidence": 0.93,
})
assert snd.enviado[-1]["payload"] == "la clave del router es 1234"   # recupero lo guardado
assert snd.enviado[-1]["target"] == {"kind": "self", "ref": "123456789"}
print("   Sender recibio (rebote):", snd.enviado[-1])

# 4) "a las 12 recuérdame lo del aceite"  -> remind FUTURO -> Scheduler
linea("4) REMIND futuro  ->  debe ir al Scheduler con la hora neutralizada")
orq.despachar({
    "action": "remind", "when": "2026-06-19T12:00:00-05:00",
    "target": {"kind": "self", "ref": "123456789"},
    "payload": "lo del aceite",
    "raw_text": "a las 12 recuérdame lo del aceite", "confidence": 0.95,
})
assert len(sch.jobs) == 1
assert sch.jobs[-1]["fire_at"] == "2026-06-19T12:00:00-05:00"
assert sch.jobs[-1]["intent"]["when"] is None      # <- hora neutralizada al programar
print("   Scheduler recibio job:", sch.jobs[-1]["fire_at"],
      "| intent.when =", sch.jobs[-1]["intent"]["when"])

# 4b) SIMULAMOS QUE LLEGAN LAS 12: el Scheduler reinyecta el intent guardado.
linea("4b) Llegan las 12  ->  el Scheduler reinyecta -> ahora SI llega al Sender, y NO se reprograma")
sender_antes = len(snd.enviado)
jobs_antes = len(sch.jobs)
orq.despachar(sch.jobs[-1]["intent"])              # reinyeccion
assert len(snd.enviado) == sender_antes + 1        # llego al usuario
assert snd.enviado[-1]["payload"] == "lo del aceite"
assert len(sch.jobs) == jobs_antes                 # <- NO volvio a programarse (anti-bucle OK)
print("   Sender recibio el recordatorio:", snd.enviado[-1])
print("   Scheduler sigue con", len(sch.jobs), "job (no se duplico) -> anti-bucle confirmado")

# 5) "a las 8 mándale a mi mamá que no me espere a cenar"  -> send FUTURO -> Scheduler
linea("5) SEND futuro  ->  tambien al Scheduler (lo futuro SIEMPRE difiere)")
orq.despachar({
    "action": "send", "when": "2026-06-19T20:00:00-05:00",
    "target": {"kind": "contact", "ref": "mi mamá"},
    "payload": "que no me espere a cenar",
    "raw_text": "a las 8 mándale a mi mamá que no me espere a cenar", "confidence": 0.9,
})
assert len(sch.jobs) == 2
assert sch.jobs[-1]["intent"]["action"] == "send"
assert sch.jobs[-1]["intent"]["when"] is None
print("   Scheduler recibio job:", sch.jobs[-1]["fire_at"],
      "| accion diferida =", sch.jobs[-1]["intent"]["action"])

# 6) ruido ininteligible  -> unknown -> Sender pide reformular
linea("6) UNKNOWN  ->  el bot pide reformular (default defensivo)")
orq.despachar({
    "action": "unknown", "when": None,
    "target": {"kind": "self", "ref": "123456789"},
    "payload": "",
    "raw_text": "blablabla ruido", "confidence": 0.3,
})
assert snd.enviado[-1]["payload"] == "no entendí, reformulá"
print("   Sender recibio:", snd.enviado[-1])


# ============================================================================
print("\n" + "=" * 70)
print("RESUMEN")
print(f"  Sender   recibio {len(snd.enviado)} mensajes")
print(f"  Memoria  guardo  {len(mem.guardado)} cosas")
print(f"  Scheduler tiene  {len(sch.jobs)} jobs diferidos")
print("\n  ✅ TODAS LAS PRUEBAS PASARON — la lógica de ruteo funciona end-to-end.")
print("=" * 70)
