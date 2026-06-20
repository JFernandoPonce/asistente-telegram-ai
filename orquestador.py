"""
Orquestador — el "repartidor" del asistente.

Es la caja del CENTRO del pipeline:
    voz -> Bot -> Transcripcion -> LLM -> [ORQUESTADOR] -> Scheduler/Memoria/Sender -> accion

Su unico trabajo es ENRUTAR. No interpreta, no guarda, no resuelve destinos,
no toca internet. Lee el Intent (la "ficha" ya armada por el LLM) y decide a que
caja llamar y con que forma minima. Toda la logica de negocio vive en otras cajas.

Diseno (Opcion A — puertos inyectados):
    El Orquestador recibe sus 3 cajas downstream + un reloj como dependencias.
    No sabe que hay detras de cada una; solo que cumplen la "forma" (puerto) de abajo.
    Eso permite probarlo HOY con cajas de carton, antes de que existan las reales.
"""

from typing import Protocol, Callable


# ----------------------------------------------------------------------------
# PUERTOS — la "boca" que cada caja downstream debe exponer.
# El Orquestador habla con estas formas, no con implementaciones concretas.
# ----------------------------------------------------------------------------
class SchedulerPort(Protocol):
    def schedule(self, job: dict) -> None: ...          # Frontera 1: recibe {fire_at, intent}


class MemoriaPort(Protocol):
    def handle(self, message: dict) -> dict: ...         # Frontera 2: union etiquetada por 'op'


class SenderPort(Protocol):
    def send(self, signal: dict) -> None: ...            # Frontera 3: recibe {target, payload}


Clock = Callable[[], str]   # devuelve "ahora" como string ISO-8601 con offset


# ----------------------------------------------------------------------------
# EL ORQUESTADOR
# ----------------------------------------------------------------------------
class Orquestador:
    def __init__(self, scheduler: SchedulerPort, memoria: MemoriaPort,
                 sender: SenderPort, clock: Clock):
        self.scheduler = scheduler
        self.memoria = memoria
        self.sender = sender
        self.clock = clock

    def despachar(self, intent: dict) -> None:
        """Puerta unica. La usan el LLM (camino normal) y el Scheduler (camino diferido)."""

        # (1) REGLA ANTI-BUCLE: todo lo FUTURO va siempre al Scheduler.
        #     Se neutraliza when=None en la copia que viaja, para que cuando el
        #     Scheduler la reinyecte al disparar, caiga en la rama "ahora" y NO
        #     se reprograme infinito.
        if intent.get("when") is not None:
            job = {
                "fire_at": intent["when"],
                "intent": {**intent, "when": None},   # misma ficha, hora neutralizada
            }
            self.scheduler.schedule(job)
            return

        # (2) Es "ahora": repartir segun la accion.
        action = intent.get("action")

        if action in ("send", "remind"):
            # Identicos en el reparto: el LLM ya lleno 'target'
            # (contact para send; self/chat_id para remind). El Orquestador no lo sintetiza.
            self.sender.send({"target": intent["target"], "payload": intent["payload"]})

        elif action == "save":
            # Guardar es para uno mismo: content + texto original + timestamp. Sin target.
            self.memoria.handle({
                "op": "save",
                "content": intent["payload"],
                "source_text": intent["raw_text"],
                "saved_at": self.clock(),
            })
            # v1: guardar NO avisa al usuario (asi quedo congelado el contrato).

        elif action == "recall":
            # recall REBOTA: Memoria devuelve un result, que mandamos de vuelta al usuario.
            respuesta = self.memoria.handle({"op": "recall", "query": intent["payload"]})
            self.sender.send({"target": intent["target"], "payload": respuesta["result"]})

        else:
            # "unknown" + default defensivo: cualquier accion fuera del enum cerrado
            # cae aqui en vez de romper. El bot pide reformular.
            self.sender.send({
                "target": intent.get("target"),
                "payload": "no entendí, reformulá",
            })
