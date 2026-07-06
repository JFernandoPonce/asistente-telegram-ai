"""
bot.py — punto de entrada + COSTURA de integracion (Stage A).

Stage A cablea el grafo persistente SIN tocar Telegram en el camino diferido:

    /recuerda (inyector temporal)
              |
              v
        [ Orquestador ]  --schedule(job)-->  [ SchedulerAdapter ]  --programar-->  [ Scheduler (scheduler.db) ]
              ^                                                                            |
              |                                                                            | tick() cada 15s (JobQueue)
              +------------------------- despachar(intent, when=null) --------------------+
              |
              v
        [ StubSender ]  (por ahora solo loguea; en Stage B lo reemplaza sender.py real)

Piezas PURAS (sin Telegram) al nivel de modulo -> se pueden probar en aislamiento
(ver prueba_integracion.py). Todo lo de Telegram vive dentro de main(), asi este
archivo se importa sin PTB ni token para las pruebas offline del cableado.

Archivos CONGELADOS que este modulo NO toca: orquestador.py, memoria.py, scheduler.py.
La reconciliacion de nombre schedule<->programar vive AQUI (en la costura), no en ellos.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from orquestador import Orquestador
from memoria import Memoria
from scheduler import Scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Ecuador = UTC-05:00, sin horario de verano. Un solo offset fijo.
_TZ_EC = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# PIEZAS PURAS (probables sin Telegram)
# ---------------------------------------------------------------------------
def reloj_iso() -> str:
    """Clock del Orquestador: 'ahora' como ISO-8601 con offset (para saved_at de Memoria)."""
    return datetime.now(_TZ_EC).isoformat()


class StubSender:
    """
    Cartón que cumple SenderPort (Frontera 3): send({target, payload}).
    Stage A: no toca Telegram, solo loguea y guarda lo enviado (para pruebas).
    Stage B: se reemplaza por sender.py real (resuelve self.ref=chat_id + puente async).
    """
    def __init__(self):
        self.enviados = []

    def send(self, signal: dict) -> None:
        self.enviados.append(signal)
        logger.info("[SENDER-STUB] mandaría a %s: %r",
                    signal.get("target"), signal.get("payload"))


class SchedulerAdapter:
    """
    Reconciliacion de la Frontera 1 en la costura:
    el Orquestador llama .schedule(job) (SchedulerPort); el Scheduler real
    expone .programar(job). Aqui se traduce, sin tocar ningun archivo congelado.
    Ademas surfacea el ack: si el Scheduler rechaza (fecha ilegible/pasada) se loguea,
    en vez de tragarselo en silencio.
    """
    def __init__(self, scheduler: Scheduler):
        self._sched = scheduler

    def schedule(self, job: dict) -> None:
        ack = self._sched.programar(job)
        if not ack.get("ok"):
            logger.warning("[SCHED] job rechazado: %s", ack.get("motivo"))
        return None


def construir_grafo(db_memoria: str = "memoria.db",
                    db_scheduler: str = "scheduler.db",
                    sender=None):
    """
    Arma Memoria + Orquestador + Scheduler ya cableados y resuelve el NUDO de construccion.

    El nudo: el Scheduler necesita `despachar` (=orq.despachar) al construirse, y el
    Orquestador necesita el scheduler. Se rompe con late-binding: el Scheduler recibe una
    lambda que resuelve `orq` recien cuando dispara (tick), momento en que `orq` ya existe.
    """
    memoria = Memoria(db_memoria)
    if sender is None:
        sender = StubSender()

    # late-binding: la lambda NO se ejecuta ahora; al correr (en tick) `orq` ya está ligado.
    sched = Scheduler(despachar=lambda intent: orq.despachar(intent), db_path=db_scheduler)
    adapter = SchedulerAdapter(sched)
    orq = Orquestador(scheduler=adapter, memoria=memoria, sender=sender, clock=reloj_iso)

    return orq, sched, sender


def construir_intent_remind(chat_id, segundos: int, texto: str, raw_text: str = None) -> dict:
    """
    Inyector temporal de Intent (hasta que exista la caja upstream LLM).
    Arma un Intent 'remind' autocontenido: target.self.ref = chat_id (D-CAP-4), when futuro.
    """
    fire_at = (datetime.now(_TZ_EC) + timedelta(seconds=segundos)).isoformat()
    return {
        "action": "remind",
        "when": fire_at,
        "target": {"kind": "self", "ref": chat_id},
        "payload": texto,
        "raw_text": raw_text if raw_text is not None else texto,
        "confidence": 1.0,
    }


# ---------------------------------------------------------------------------
# ENTRADA REAL (Telegram) — imports de PTB confinados aqui a proposito
# ---------------------------------------------------------------------------
def main() -> None:
    from dotenv import load_dotenv
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, filters, ContextTypes,
    )

    from sender import Sender

    load_dotenv()
    token = os.environ["BOT_TOKEN"]   # revienta claro si falta

    # La app se crea ANTES del grafo: el Sender real necesita `application` (puente
    # sync->async via create_task). Se inyecta el Sender real en lugar del StubSender.
    app = Application.builder().token(token).build()
    sender = Sender(app)
    orq, sched, _sender = construir_grafo("memoria.db", "scheduler.db", sender=sender)

    # --- Inyector temporal de Intent: /recuerda <segundos> <texto...> ---
    async def cmd_recuerda(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        chat_id = update.effective_chat.id
        args = context.args
        if len(args) < 2 or not args[0].lstrip("-").isdigit():
            await update.message.reply_text("Uso: /recuerda <segundos> <texto>")
            return
        segundos = int(args[0])
        texto = " ".join(args[1:])
        intent = construir_intent_remind(chat_id, segundos, texto, update.message.text)
        orq.despachar(intent)   # camino diferido -> Scheduler (via adapter)
        await update.message.reply_text(
            f"⏰ (stub) intent 'remind' despachado: en {segundos}s → {texto!r}. "
            f"Al vencer verás el log [SENDER-STUB] en consola."
        )

    # --- Echo conservado: smoke basico de transporte (texto no-comando) ---
    async def echo(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        logger.info("Recibido de %s: %s", update.effective_user.id, update.message.text)
        await update.message.reply_text(update.message.text)

    app.add_handler(CommandHandler("recuerda", cmd_recuerda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # --- Heartbeat prescrito por la Spec: run_repeating(tick, 15, first=0) ---
    async def _latido(context: "ContextTypes.DEFAULT_TYPE") -> None:
        sched.tick()   # sincrono; el Sender encola la corrutina (create_task), no bloquea

    if app.job_queue is None:
        raise RuntimeError(
            "JobQueue no disponible: instala 'python-telegram-bot[job-queue]' "
            "(ver requirements.txt)."
        )
    app.job_queue.run_repeating(_latido, interval=15, first=0)

    logger.info("Bot arrancado (Stage B: Scheduler + Sender real cableados). Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
