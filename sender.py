"""
sender.py — Frontera 3 (Orq -> Sender). Entrega el mensaje al destinatario. Stage B.

Contrato congelado: send({ target: {kind, ref}, payload }) -> None.

Tabla de resolucion por `kind` (dispatcher pensado para CRECER, no para cerrarse):
  self    -> `ref` YA es el chat_id (horneado en captura, D-CAP-4) -> entrega directo.
  contact -> B1: `ref` es texto crudo ("mi papá"), NO hay chat_id -> no hay a quien entregar.
             No revienta: loguea claro. B2 (futuro) REEMPLAZA esta rama por un directorio
             contacto->chat_id, sin tocar esta frontera ni el Orquestador.
  <otro>  -> defensivo: loguea y sigue.

Puente sync->async (el corazon de Stage B): `send` es SINCRONO (lo llaman el tick del
Scheduler y los handlers), pero `bot.send_message` es async. No se puede `await` aqui.
Se encola la corrutina en el event loop que YA corre, via `application.create_task(...)`.
Sync empuja, el loop ejecuta; el tick no se bloquea.

La logica se parte en dos a proposito:
  _resolver(signal) -> PLAN   (PURA: sin efectos, sin loop -> testeable en aislamiento)
  send(signal)                (aplica el plan: encola la corrutina o loguea)
"""

import logging

logger = logging.getLogger(__name__)

# Presentacion. PROVISIONAL: hoy el unico productor es /recuerda -> remind, asi que TODO
# self es un recordatorio. Cuando existan recall/send con destino self, este prefijo debe
# venir de la senal (sibling aditivo en Frontera 3, patron owner/ADR-0005), no fijo aqui.
PREFIJO_RECORDATORIO = "⏰ Recordatorio: "


class Sender:
    def __init__(self, application):
        # application = Application de PTB. Se usa .create_task (puente) y .bot.send_message.
        self._app = application

    # --- PURA: decide a donde y con que texto, o por que NO se entrega ---
    def _resolver(self, signal: dict) -> dict:
        target = signal.get("target") or {}
        payload = signal.get("payload", "")
        kind = target.get("kind")
        ref = target.get("ref")

        if kind == "self":
            return {"entregar": True, "chat_id": ref,
                    "texto": f"{PREFIJO_RECORDATORIO}{payload}"}

        if kind == "contact":
            return {"entregar": False,
                    "motivo": f"kind:contact ref={ref!r} sin directorio contacto->chat_id "
                              f"(B1; Telegram no permite iniciar chat)"}

        return {"entregar": False, "motivo": f"kind desconocido {kind!r}"}

    # --- Aplica el plan. Cumple SenderPort: send(signal) -> None ---
    def send(self, signal: dict) -> None:
        plan = self._resolver(signal)
        if plan["entregar"]:
            # Puente sync->async: encola en el loop corriendo. NO await.
            self._app.create_task(
                self._app.bot.send_message(chat_id=plan["chat_id"], text=plan["texto"])
            )
            logger.info("[SENDER] entregando a chat_id=%s: %r",
                        plan["chat_id"], plan["texto"])
        else:
            logger.warning("[SENDER] NO entregado (%s) | payload=%r",
                           plan["motivo"], signal.get("payload"))
