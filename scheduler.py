"""
Scheduler — alarma persistente (Opción C: el reloj vive en la base).

Caja TONTA: retiene trabajos diferidos hasta su hora y los reinyecta al
Orquestador. No conoce acciones, no abre el `intent`, no interpreta.

Spec congelada v1: "Spec ejecutable — Scheduler (C: reloj en la base)".
Frontera de entrada congelada: Contrato Orquestador · Frontera 1.

Sin dependencia de Telegram a propósito: expone `programar(job)` y `tick()`.
Quién llama a `tick()` cada 15 s (la JobQueue de PTB) es integración en bot.py.
Eso mantiene el Scheduler probable en aislamiento.
"""

import json
import sqlite3
import time
from datetime import datetime


SCHEMA = """
CREATE TABLE IF NOT EXISTS recordatorios (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  fire_at      INTEGER NOT NULL,   -- epoch UTC (segundos). UNICO comparador del poller.
  intent_json  TEXT    NOT NULL,   -- el Intent serializado (json). CAJA OPACA. when=null.
  status       TEXT    NOT NULL,   -- 'pendiente' | 'disparado'
  created_at   INTEGER NOT NULL    -- epoch UTC en que se programo (trazabilidad)
);
CREATE INDEX IF NOT EXISTS idx_recordatorios_due
  ON recordatorios (status, fire_at);
"""


class Scheduler:
    def __init__(self, despachar, db_path="scheduler.db"):
        # `despachar` = puerta unica del Orquestador, inyectada (DI). El Scheduler
        # reinyecta sin conocer el interior del Orquestador.
        self.despachar = despachar
        # check_same_thread=False: el constructor abre la oficina por la manana,
        # pero el `tick` (sereno) corre en el hilo de la JobQueue. Decision de
        # implementacion consciente; no mueve ninguna frontera.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)   # idempotente: abrir 1 o N veces, mismo estado
        self.conn.commit()

    # --- Verbo 1: recibir encomienda ----------------------------------------
    def programar(self, job):
        """Lo llama el Orquestador cuando intent.when != null. Recibe {fire_at, intent}."""
        try:
            dt = datetime.fromisoformat(job["fire_at"])        # exige offset (aware)
        except (ValueError, KeyError, TypeError):
            return {"ok": False, "motivo": "fire_at no parseable"}
        fire_epoch = int(dt.timestamp())                        # ISO aware -> epoch UTC
        now_epoch = int(time.time())
        if fire_epoch <= now_epoch:
            return {"ok": False, "motivo": "fire_at en el pasado"}
        cur = self.conn.execute(
            "INSERT INTO recordatorios (fire_at, intent_json, status, created_at) "
            "VALUES (?, ?, 'pendiente', ?)",
            (fire_epoch, json.dumps(job["intent"]), now_epoch),
        )
        self.conn.commit()
        return {"ok": True, "id": cur.lastrowid}

    # --- Verbo 2: la ronda ---------------------------------------------------
    def tick(self):
        """Heartbeat. Reclama lo vencido de forma atomica y lo reinyecta."""
        now = int(time.time())
        filas = self.conn.execute(
            "SELECT id, intent_json FROM recordatorios "
            "WHERE status='pendiente' AND fire_at <= ? ORDER BY fire_at", (now,)
        ).fetchall()
        for fila in filas:
            # Claim atomico marcar-primero (at-most-once): tacho ANTES de entregar.
            cur = self.conn.execute(
                "UPDATE recordatorios SET status='disparado' "
                "WHERE id=? AND status='pendiente'", (fila["id"],)
            )
            self.conn.commit()
            if cur.rowcount == 1:                 # gane el claim -> es mia
                intent = json.loads(fila["intent_json"])
                self.despachar(intent)            # reinyeccion (intent ya trae when=null)


# ===========================================================================
# Autoprueba: simulacro con maniqui. Corre solo al ejecutar el archivo a mano.
# No quema el edificio (Telegram); usa un cartero falso que anota entregas.
# ===========================================================================
if __name__ == "__main__":
    import os
    import tempfile
    from datetime import timedelta, timezone

    db_file = os.path.join(tempfile.gettempdir(), "scheduler_test.db")
    if os.path.exists(db_file):
        os.remove(db_file)

    entregas = []                       # el "papel" donde el cartero falso anota
    def despachar_falso(intent):
        entregas.append(intent)

    sched = Scheduler(despachar_falso, db_path=db_file)
    fallos = []

    # --- Escena 1: camino feliz + at-most-once ---
    pronto = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    job = {"fire_at": pronto,
           "intent": {"action": "send", "when": None,
                      "target": {"kind": "contact", "ref": "mi papa"},
                      "payload": "lo del aceite"}}
    ack = sched.programar(job)
    assert ack["ok"], "programar deberia aceptar una fecha futura legible"

    # Antes de la hora: la ronda no debe disparar nada.
    sched.tick()
    if len(entregas) != 0:
        fallos.append("ESCENA 1: disparo anticipado (la ronda solo dispara lo vencido)")

    time.sleep(1.1)
    sched.tick()          # ya vencio
    sched.tick()          # segunda ronda: NO debe re-disparar (ya esta tachado)
    if len(entregas) != 1:
        fallos.append(f"ESCENA 1: se esperaba 1 entrega, hubo {len(entregas)} (at-most-once roto)")
    fila = sched.conn.execute("SELECT status FROM recordatorios WHERE id=?",
                              (ack["id"],)).fetchone()
    if fila["status"] != "disparado":
        fallos.append("ESCENA 1: el paquete no quedo tachado tras dispararse")

    # --- Escena 2: bot caido -> vencido durante la caida se dispara igual ---
    entregas.clear()
    pasado_epoch = int(time.time()) - 3600       # vencio hace 1 h (bot estaba caido)
    sched.conn.execute(
        "INSERT INTO recordatorios (fire_at, intent_json, status, created_at) "
        "VALUES (?, ?, 'pendiente', ?)",
        (pasado_epoch,
         json.dumps({"action": "remind", "when": None,
                     "target": {"kind": "self", "ref": 12345},
                     "payload": "era para las 12:00"}),
         pasado_epoch),
    )
    sched.conn.commit()
    sched.tick()          # primera ronda al "reabrir la oficina"
    if len(entregas) != 1:
        fallos.append(f"ESCENA 2: vencido NO disparado, se esperaba 1, hubo {len(entregas)} (cero-perdida roto)")

    # --- Validaciones de frontera del mostrador ---
    if sched.programar({"fire_at": "garabato", "intent": {}})["ok"]:
        fallos.append("MOSTRADOR: acepto fecha ilegible (deberia rechazar)")
    if sched.programar({"fire_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                        "intent": {}})["ok"]:
        fallos.append("MOSTRADOR: acepto fecha pasada (deberia rechazar)")

    # --- Veredicto ---
    if fallos:
        print("FALLOS:")
        for f in fallos:
            print("  -", f)
        raise SystemExit(1)
    print("OK — Escena 1 (camino feliz + at-most-once): paso")
    print("OK — Escena 2 (bot caido, cero perdida): paso")
    print("OK — Mostrador (rechaza ilegible y pasado): paso")
    print("Todas las escenas pasaron.")
