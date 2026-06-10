# 🤖 Asistente Telegram AI

Bot de Telegram diseñado como base para un asistente personal con inteligencia artificial. Implementado con arquitectura asíncrona (python-telegram-bot v20+) y preparado para integrar un orquestador LLM en la capa de procesamiento.

El objetivo del proyecto es construir un loop agéntico completo: recepción de mensajes de voz o texto → transcripción → detección de intención → ejecución de acciones mediante herramientas (MCPs, APIs, memoria persistente).

---

## 🏗️ Arquitectura

```
Usuario (Telegram)
        │
        ▼
   [ bot.py ]  ← Handler de mensajes (texto / voz)
        │
        ▼
   [ Costura ]  ← Aquí entra el orquestador LLM
        │
        ├── Memoria persistente (Obsidian / vaults)
        ├── Herramientas MCP (TradingView, Calendar, etc.)
        └── Respuesta al usuario
```

El proyecto sigue un principio de separación clara: el bot maneja el transporte (Telegram), la costura maneja la lógica (LLM + tools). Cambiar de modelo o agregar herramientas no requiere tocar el handler.

---

## ✨ Estado actual

- [x] Recepción de mensajes de texto
- [x] Logging con trazabilidad por usuario
- [x] Configuración segura via `.env` (token nunca en código)
- [x] Arquitectura preparada para orquestador LLM
- [ ] Transcripción de mensajes de voz (próximo paso)
- [ ] Integración con Claude API como orquestador
- [ ] Memoria persistente con vaults Obsidian vía MCP
- [ ] Ejecución de skills personalizadas

---

## 🛠️ Stack

| Capa | Tecnología |
|---|---|
| Transporte | Telegram Bot API |
| Framework | python-telegram-bot 22.7 (async) |
| Configuración | python-dotenv |
| Orquestador (próximo) | Claude API (Anthropic) |
| Memoria (próximo) | MCP + Obsidian |

---

## 🚀 Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/JFernandoPonce/asistente-telegram-ai.git
cd asistente-telegram-ai
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar el token
```bash
cp .env.example .env
# Editar .env y pegar el token de BotFather
```

### 4. Ejecutar
```bash
python bot.py
```

---

## ⚙️ Configuración

Crea un archivo `.env` en la raíz del proyecto:

```env
BOT_TOKEN=pega_aqui_tu_token_de_botfather
```

Para obtener un token: habla con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot`.

---

## 📁 Estructura del proyecto

```
asistente-telegram-ai/
├── bot.py              # Handler principal y configuración del bot
├── requirements.txt    # Dependencias Python
├── .env.example        # Plantilla de variables de entorno
├── .gitignore          # Excluye .env y archivos sensibles
└── README.md
```

---

## 🧠 Contexto y dirección del proyecto

Este bot es el punto de entrada de un sistema agéntico más amplio basado en la arquitectura de **harness engineering**: el bot es solo el canal de comunicación; la capacidad del asistente la definen las herramientas habilitadas alrededor (memoria, skills, MCPs).

El diseño está inspirado en el patrón **Loop para agentes**: evento de entrada → agente con contexto + tools → respuesta con acción. La separación entre transporte y lógica permite evolucionar el orquestador de manera independiente.

---

## 🔒 Seguridad

- El token nunca se incluye en el código fuente
- `.env` está en `.gitignore` por defecto
- `.env.example` sirve como documentación sin exponer credenciales

---

*Desarrollado por [Juan Fernando Ponce](https://github.com/JFernandoPonce)*
