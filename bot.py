"""
bot.py — punto de entrada + COSTURA de integracion (Stage A/B + UPSTREAM U1).

Camino diferido (Stage A/B, intacto):

        [ Orquestador ]  --schedule(job)-->  [ SchedulerAdapter ]  --programar-->  [ Scheduler (scheduler.db) ]
              ^                                                                            |
              |                                                                            | tick() cada 15s (JobQueue)
              +------------------------- despachar(intent, when=null) --------------------+
              |
              v
        [ Sender real ]  (self -> chat_id; contact -> B1 log)

UPSTREAM U1 (nuevo): el andamio /recuerda se RETIRA. Ahora un mensaje de TEXTO entra por el
verdadero pipeline de interpretacion:

    texto -> construir_context -> interpretar(text, ctx)  [interpreter.py: Gemini extrae / Python valida]
          -> Intent congelado -> orq.despachar     (o unknown -> el bot repregunta)

`construir_context` es el MISMO helper que reutilizara U3 (voz): arma el carril `context`
opaco (now + tz + sender) que el Contrato Captura define para las fronteras 5 y 6.

Piezas PURAS (sin Telegram) al nivel de modulo -> se prueban en aislamiento
(prueba_integracion.py, prueba_bot_context.py). Todo lo de Telegram vive dentro de main().

Archivos CONGELADOS que este modulo NO toca: orquestador.py, memoria.py, scheduler.py, sender.py.
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
_TZ_NAME = "America/Guayaquil"   # nombre IANA para el carril context.tz


# ---------------------------------------------------------------------------
# PIEZAS PURAS (probables sin Telegram)
# ---------------------------------------------------------------------------
def reloj_iso() -> str:
    """Clock del Orquestador: 'ahora' como ISO-8601 con offset (para saved_at de Memoria)."""
    return datetime.now(_TZ_EC).isoformat()


def construir_context(update) -> dict:
    """
    Arma el carril `context` opaco del Contrato Captura (fronteras 5 y 6).
    Fuente de la verdad:
      - now    : marca de tiempo del mensaje (message.date, en UTC) convertida a _TZ_EC.
                 Se usa message.date y NO datetime.now() para ser inmune al lag de proceso
                 y a un backlog tras reinicio (el 'ahora' es el del envio, no el del handler).
      - tz     : zona del que manda (single-tenant: constante; seam multi-inquilino a futuro).
      - sender : chat_id (mismo int que espera el Sender congelado) + nombre.

    Reutilizado TAL CUAL por U3 (voz): la unica diferencia entre texto y voz es que la voz
    pasa antes por Transcripcion; el context se arma igual desde el `update`.
    """
    msg_date = update.message.date
    if msg_date.tzinfo is None:                 # defensivo: PTB da UTC aware, pero por si acaso
        msg_date = msg_date.replace(tzinfo=timezone.utc)
    now_iso = msg_date.astimezone(_TZ_EC).isoformat()

    user = update.effective_user
    return {
        "now": now_iso,
        "tz": _TZ_NAME,
        "sender": {
            "chat_id": update.effective_chat.id,          # int -> coincide con Sender/D-CAP-4
            "name": user.first_name if user else None,
        },
    }


def _fmt_when(when_iso) -> str:
    """when ISO -> etiqueta humana corta; None -> 'ahora'."""
    if not when_iso:
        return "ahora"
    try:
        return datetime.fromisoformat(when_iso).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return str(when_iso)


def confirmar(intent: dict) -> str:
    """Acuse humano corto de lo que se ENTENDIO (no del resultado de la ejecucion).
    Vive en la capa bot (presentacion): iterable sin tocar contratos."""
    action = intent["action"]
    payload = intent.get("payload", "")
    when = _fmt_when(intent.get("when"))
    target = intent.get("target", {})

    if action == "unknown":
        return "🤔 No te entendí bien. ¿Me lo repites de otra forma?"
    if action == "remind":
        return f"⏰ Anotado. Te recuerdo «{payload}» ({when})."
    if action == "send":
        ref = target.get("ref")
        return f"✉️ Entendido: enviar a {ref} «{payload}» ({when})."
    if action == "save":
        return f"💾 Guardado: «{payload}»."
    if action == "recall":
        return f"🔎 Busco: «{payload}»."
    return f"✔️ {action}: «{payload}» ({when})."


class StubSender:
    """
    Cartón que cumple SenderPort (Frontera 3): send({target, payload}).
    Se conserva como doble de prueba para prueba_integracion.py (sin PTB ni token).
    En produccion main() inyecta el Sender real (sender.py).
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


# ---------------------------------------------------------------------------
# ENTRADA REAL (Telegram) — imports de PTB confinados aqui a proposito
# ---------------------------------------------------------------------------
def main() -> None:
    from dotenv import load_dotenv
    from telegram import Update
    from telegram.ext import (
        Application, MessageHandler, filters, ContextTypes,
    )

    from sender import Sender
    from interpreter import interpretar   # caja LLM upstream (Gemini extrae / Python valida)

    load_dotenv()
    token = os.environ["BOT_TOKEN"]   # revienta claro si falta

    # La app se crea ANTES del grafo: el Sender real necesita `application` (puente
    # sync->async via create_task). Se inyecta el Sender real en lugar del StubSender.
    app = Application.builder().token(token).build()
    sender = Sender(app)
    orq, sched, _sender = construir_grafo("memoria.db", "scheduler.db", sender=sender)

    # --- UPSTREAM U1: mensaje de texto -> interpretar -> despachar ---
    #     Reemplaza el andamio /recuerda y el echo. La voz (U3) entrara por el mismo
    #     construir_context, agregando solo el paso de Transcripcion antes de interpretar.
    async def on_text(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        text = update.message.text
        ctx = construir_context(update)
        logger.info("Recibido de %s: %r", ctx["sender"]["chat_id"], text)

        intent = await interpretar(text, ctx)   # async: Gemini + validador determinista

        if intent["action"] == "unknown":
            await update.message.reply_text(confirmar(intent))
            return

        orq.despachar(intent)                   # sync; camino inmediato o diferido segun `when`
        await update.message.reply_text(confirmar(intent))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # --- Heartbeat prescrito por la Spec: run_repeating(tick, 15, first=0) ---
    async def _latido(context: "ContextTypes.DEFAULT_TYPE") -> None:
        sched.tick()   # sincrono; el Sender encola la corrutina (create_task), no bloquea

    if app.job_queue is None:
        raise RuntimeError(
            "JobQueue no disponible: instala 'python-telegram-bot[job-queue]' "
            "(ver requirements.txt)."
        )
    app.job_queue.run_repeating(_latido, interval=15, first=0)

    logger.info("Bot arrancado (U1: upstream texto->LLM->Intent + Scheduler + Sender real). Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
