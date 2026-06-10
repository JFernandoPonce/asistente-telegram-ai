import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 1. Lee el archivo .env y mete sus variables en el entorno del proceso.
load_dotenv()

# 2. Lee el token. Con corchetes a propósito: si falta, el programa revienta
#    de inmediato con un error claro en vez de arrancar a medias.
TOKEN = os.environ["BOT_TOKEN"]

# 3. Logging con nivel y timestamp (mejor que print para ver qué pasó).
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# 4. Handler: PTB lo llama cuando llega un mensaje que matchea su filtro.
#    Es async porque PTB v20+ es asíncrono.
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = update.message.text                                    # 5. contrato de entrada (por ahora)
    logger.info("Recibido de %s: %s", update.effective_user.id, texto)  # 6. trazabilidad
    # 7. LA COSTURA: hoy devuelve el mismo texto. Mañana, aquí entran
    #    transcripcion -> LLM(Intent) -> orquestador.
    await update.message.reply_text(texto)


def main() -> None:
    app = Application.builder().token(TOKEN).build()               # 8. arma la app con el token
    # 9. registra el handler: texto que NO sea comando (/algo)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    logger.info("Bot arrancado. Esperando mensajes (polling)...")
    # 10. abre la PUERTA: getUpdates en loop. No necesita URL pública (vs webhook).
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":   # 11. solo corre si ejecutas este archivo directamente
    main()
