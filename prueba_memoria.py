"""
Prueba de la caja MEMORIA real (SQLite).

Lo que demuestra:
  1) Guardar y recuperar funciona para un mismo dueño.
  2) AISLAMIENTO multi-inquilino: la nota de un dueño NO aparece en el recall de otro.
     (Este es el corazon de ADR-0005: el agua del cuarto de Ana no sale por la llave de Luis.)
  3) recall sin coincidencia devuelve un mensaje amable, no un error.
  4) INTEGRACION: el Orquestador real + la Memoria real (SQLite) hacen el ciclo
     guardar -> recuperar de punta a punta, respetando el dueño.

Usa una base ":memory:" (en RAM, desechable) -> no toca tu disco, no deja rastro.
"""

from memoria import Memoria
from orquestador import Orquestador


def linea(t):
    print("\n" + "-" * 70 + f"\n{t}")


# IDs de prueba (chat_id de Telegram simulados)
ANA = 11111
LUIS = 22222


# ============================================================================
# 1) GUARDAR Y RECUPERAR (un solo dueño)
# ============================================================================
linea("1) Guardar y recuperar para el mismo dueño")
mem = Memoria(":memory:")

mem.handle({"op": "save", "owner": ANA, "content": "la clave del router es 1234",
            "source_text": "guarda esto: la clave del router es 1234",
            "saved_at": "2026-06-19T10:00:00-05:00"})

r = mem.handle({"op": "recall", "owner": ANA, "query": "clave del router"})
assert r["result"] == "la clave del router es 1234"
print("   Ana guardo y recupero:", r["result"])


# ============================================================================
# 2) AISLAMIENTO ENTRE DUEÑOS  (lo mas importante)
# ============================================================================
linea("2) Aislamiento: Luis NO puede ver la nota de Ana")

# Luis guarda algo propio
mem.handle({"op": "save", "owner": LUIS, "content": "mi cita con el dentista es el martes",
            "source_text": "guarda que mi cita con el dentista es el martes",
            "saved_at": "2026-06-19T11:00:00-05:00"})

# Luis pide "clave del router" -> existe, pero es de ANA -> Luis NO debe verla
r_luis = mem.handle({"op": "recall", "owner": LUIS, "query": "clave del router"})
assert r_luis["result"] == "No encontré nada sobre eso."
print("   Luis pide 'clave del router' ->", r_luis["result"], "(correcto: es de Ana)")

# Cada quien SI ve lo suyo
assert mem.handle({"op": "recall", "owner": ANA,  "query": "router"})["result"] == "la clave del router es 1234"
assert mem.handle({"op": "recall", "owner": LUIS, "query": "dentista"})["result"] == "mi cita con el dentista es el martes"
print("   Ana ve lo de Ana, Luis ve lo de Luis -> aislamiento OK")


# ============================================================================
# 3) RECALL SIN COINCIDENCIA
# ============================================================================
linea("3) recall sin coincidencia -> mensaje amable")
r_vacio = mem.handle({"op": "recall", "owner": ANA, "query": "algo que nunca guardé"})
assert r_vacio["result"] == "No encontré nada sobre eso."
print("   ->", r_vacio["result"])

mem.cerrar()


# ============================================================================
# 4) INTEGRACION: Orquestador real + Memoria real
# ============================================================================
linea("4) Integración: el Orquestador real habla con la Memoria real (SQLite)")

class CartonSender:
    def __init__(self): self.enviado = []
    def send(self, signal): self.enviado.append(signal)

class CartonScheduler:
    def __init__(self): self.jobs = []
    def schedule(self, job): self.jobs.append(job)

def reloj_fijo(): return "2026-06-19T12:00:00-05:00"

mem2 = Memoria(":memory:")
snd = CartonSender()
orq = Orquestador(scheduler=CartonScheduler(), memoria=mem2, sender=snd, clock=reloj_fijo)

# Ana le habla al bot: "guarda esto: el wifi es MiCasa2024"
orq.despachar({
    "action": "save", "when": None,
    "target": {"kind": "self", "ref": ANA},
    "payload": "el wifi es MiCasa2024",
    "raw_text": "guarda esto: el wifi es MiCasa2024", "confidence": 0.96,
})
assert len(snd.enviado) == 0          # guardar es silencioso
print("   Ana guardo el wifi (sin respuesta, correcto)")

# Ana pide: "tráeme el wifi"  -> debe rebotar al Sender con SU dato
orq.despachar({
    "action": "recall", "when": None,
    "target": {"kind": "self", "ref": ANA},
    "payload": "wifi",
    "raw_text": "tráeme el wifi", "confidence": 0.94,
})
assert snd.enviado[-1]["payload"] == "el wifi es MiCasa2024"
print("   Ana pidio el wifi -> Sender recibio:", snd.enviado[-1]["payload"])

# Luis pide "wifi" -> NO debe recibir el de Ana
orq.despachar({
    "action": "recall", "when": None,
    "target": {"kind": "self", "ref": LUIS},
    "payload": "wifi",
    "raw_text": "tráeme el wifi", "confidence": 0.94,
})
assert snd.enviado[-1]["payload"] == "No encontré nada sobre eso."
print("   Luis pidio el wifi -> Sender recibio:", snd.enviado[-1]["payload"], "(no es suyo)")

mem2.cerrar()


# ============================================================================
print("\n" + "=" * 70)
print("  ✅ TODAS LAS PRUEBAS DE MEMORIA PASARON")
print("     guardar/recuperar OK · aislamiento entre dueños OK · integración OK")
print("=" * 70)
