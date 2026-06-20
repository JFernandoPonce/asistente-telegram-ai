"""
Memoria — la caja que guarda y recupera notas por voz.

Implementa la Frontera 2 (Orq -> Memoria), version con `owner` (ADR-0005):
    save   -> { op:"save",   owner, content, source_text, saved_at } -> { ok }
    recall -> { op:"recall", owner, query }                          -> { result }

MULTI-INQUILINO: TODO se guarda y se busca acotado por `owner` (el chat_id).
La nota de Ana NUNCA aparece en el recall de Luis.

Almacen: SQLite -> un solo archivo en disco. Gratis, sin servidor aparte, incluido
en Python (modulo `sqlite3`, cero instalacion). La ruta del archivo se INYECTA: en
pruebas usamos ":memory:" (una base en RAM, desechable, que no toca el disco).

Decisiones v1 (declaradas, no inferidas):
  - recall: busca por substring dentro de las notas del dueño; devuelve la MAS RECIENTE.
            Si no hay coincidencia -> "No encontré nada sobre eso."
  - owner:  se normaliza a texto (str) al guardar y al buscar, para ser robusto a que
            el chat_id llegue como numero o como texto (ver nota de tipo en ADR-0005).
"""

import sqlite3


class Memoria:
    def __init__(self, db_path: str = ":memory:"):
        # check_same_thread=False: el bot corre async; permitimos acceso entre hilos.
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._crear_tabla()

    def _crear_tabla(self):
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS notas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                owner       TEXT NOT NULL,
                content     TEXT NOT NULL,
                source_text TEXT,
                saved_at    TEXT NOT NULL
            )
            """
        )
        # Indice por dueño: las busquedas siempre filtran por owner -> que sean rapidas.
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_owner ON notas(owner)")
        self.con.commit()

    # --- Puerta unica. Cumple MemoriaPort: handle(message) -> dict ---
    def handle(self, message: dict) -> dict:
        op = message.get("op")
        if op == "save":
            return self._save(message)
        if op == "recall":
            return self._recall(message)
        return {"ok": False}   # op desconocida: defensivo, no rompe.

    def _save(self, m: dict) -> dict:
        try:
            self.con.execute(
                "INSERT INTO notas (owner, content, source_text, saved_at) VALUES (?, ?, ?, ?)",
                (str(m["owner"]), m["content"], m.get("source_text"), m["saved_at"]),
            )
            self.con.commit()
            return {"ok": True}
        except Exception:
            return {"ok": False}

    def _recall(self, m: dict) -> dict:
        patron = f"%{m['query']}%"
        fila = self.con.execute(
            """
            SELECT content FROM notas
            WHERE owner = ? AND content LIKE ?
            ORDER BY saved_at DESC, id DESC
            LIMIT 1
            """,
            (str(m["owner"]), patron),
        ).fetchone()
        if fila is not None:
            return {"result": fila["content"]}
        return {"result": "No encontré nada sobre eso."}

    def cerrar(self):
        self.con.close()
