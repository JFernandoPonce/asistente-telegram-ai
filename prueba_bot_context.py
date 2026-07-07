# prueba_bot_context.py — QA de las piezas puras nuevas de bot.py (sin PTB).
# Usa un `update` falso con la misma forma que PTB expone.

from datetime import datetime, timezone
import bot

fallos = []


def check(nombre, cond):
    print(f"  {'OK ' if cond else 'FALLA'}  {nombre}")
    if not cond:
        fallos.append(nombre)


# --- Fakes con la forma minima que usan construir_context ---
class FakeUser:
    def __init__(self, first_name): self.first_name = first_name

class FakeChat:
    def __init__(self, id): self.id = id

class FakeMessage:
    def __init__(self, date, text): self.date = date; self.text = text

class FakeUpdate:
    def __init__(self, date, text, chat_id, first_name):
        self.message = FakeMessage(date, text)
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser(first_name)


print("prueba_bot_context:")

# PTB entrega message.date como datetime AWARE en UTC.
# 2026-06-15 14:00 UTC == 09:00 en Ecuador (-05:00).
upd = FakeUpdate(
    date=datetime(2026, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
    text="a las 12 recuerdame lo del aceite",
    chat_id=1587374864,
    first_name="JF",
)
ctx = bot.construir_context(upd)

check("now convertido a offset -05:00", ctx["now"] == "2026-06-15T09:00:00-05:00")
check("tz = America/Guayaquil", ctx["tz"] == "America/Guayaquil")
check("chat_id es int (coincide con Sender)", ctx["sender"]["chat_id"] == 1587374864
      and isinstance(ctx["sender"]["chat_id"], int))
check("name = first_name", ctx["sender"]["name"] == "JF")
check("context tiene exactamente las 3 llaves del carril", set(ctx.keys()) == {"now", "tz", "sender"})

# defensivo: si message.date llegara naive, se asume UTC
upd2 = FakeUpdate(
    date=datetime(2026, 6, 15, 14, 0, 0),   # naive
    text="hola", chat_id=1, first_name="X",
)
ctx2 = bot.construir_context(upd2)
check("date naive -> asume UTC -> 09:00-05:00", ctx2["now"] == "2026-06-15T09:00:00-05:00")

# --- confirmar(): acuse humano por accion ---
def intent(action, **kw):
    base = {"action": action, "when": None, "target": {"kind": "self", "ref": 1},
            "payload": "x", "raw_text": "x", "confidence": 0.9}
    base.update(kw); return base

check("confirmar remind menciona hora",
      "12:00" in bot.confirmar(intent("remind", when="2026-06-15T12:00:00-05:00", payload="lo del aceite")))
check("confirmar unknown = repregunta",
      "repites" in bot.confirmar(intent("unknown")).lower())
check("confirmar send nombra al contacto",
      "mi mama" in bot.confirmar(intent("send", target={"kind": "contact", "ref": "mi mama"}, payload="ya voy")))
check("confirmar save",
      bot.confirmar(intent("save", payload="clave 1234")).startswith("💾"))
check("confirmar recall",
      bot.confirmar(intent("recall", payload="clave")).startswith("🔎"))

print(f"\nRESULTADO bot_context: {'TODOS VERDES' if not fallos else 'FALLOS: ' + str(fallos)}")
raise SystemExit(1 if fallos else 0)
