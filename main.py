from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pyodbc
from fastapi import FastAPI, HTTPException, Request

from config import load_bot_config, load_db_config
from database import ClientPekcStatus, DatabaseService
from whatsapp import EvolutionClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("hub-whatsapp-rb")

app = FastAPI(title="Hub WhatsApp RB", version="0.1.0")

bot_config = load_bot_config()
db_config = load_db_config()
db = DatabaseService(db_config, bot_config)
wa = EvolutionClient(bot_config)
states: Dict[str, Dict[str, datetime | str]] = {}
SESSION_TIMEOUT_MINUTES = 10

WELCOME_MESSAGE = (
    "👋 Bem-vindo à Central de Suporte ao RCA.\n\n"
    "Digite somente o código do cliente RB para consultar o PEKC:\n"
    "✅ Atingimento\n"
    "📌 Itens não positivados\n\n"
    "Digite 0 para sair."
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/evolution")
async def evolution_webhook(request: Request) -> Dict[str, str]:
    payload = await request.json()

    if _is_from_me(payload):
        return {"status": "ignored", "reason": "from_me"}

    phone = _extract_phone(payload)
    text = _extract_text(payload)

    if not phone or not text:
        return {"status": "ignored", "reason": "missing_phone_or_text"}

    if _is_group_message(payload):
        return {"status": "ignored", "reason": "group_message"}

    try:
        if db.is_seller_validation_enabled() and not db.is_seller_active(phone):
            logger.info("Número não autorizado: %s", phone)
            return {"status": "ignored", "reason": "seller_not_allowed"}
    except pyodbc.Error:
        logger.exception("Falha ao validar vendedor ativo")
        wa.send_text(phone, "⚠️ Não foi possível validar seu acesso agora. Tente novamente em instantes.")
        return {"status": "ok", "reason": "seller_validation_error"}

    current_state = states.get(phone)
    if _is_session_expired(current_state):
        states.pop(phone, None)
        current_state = None

    normalized_text = text.strip()

    if current_state is None:
        wa.send_text(phone, WELCOME_MESSAGE)
        _start_session(phone)
        return {"status": "ok", "reason": "welcome_sent"}

    if normalized_text == "0":
        wa.send_text(
            phone,
            "✅ Atendimento encerrado.\n\nQuando quiser, envie qualquer mensagem para iniciar novamente.",
        )
        _end_session(phone)
        return {"status": "ok", "reason": "session_closed"}

    if not _is_only_digits(normalized_text):
        _touch_session(phone)
        wa.send_text(
            phone,
            "⚠️ Formato inválido.\n\nDigite somente o código numérico do cliente RB ou 0 para sair.",
        )
        return {"status": "ok", "reason": "invalid_format"}

    cod_cliente = _extract_client_code(normalized_text)
    if not cod_cliente:
        _touch_session(phone)
        wa.send_text(
            phone,
            "⚠️ Não consegui identificar o código do cliente.\n\nTente novamente.",
        )
        return {"status": "ok", "reason": "empty_code"}

    _touch_session(phone)

    try:
        status = db.get_client_pekc_status(cod_cliente)
    except pyodbc.Error:
        logger.exception("Erro ao consultar PEKC para cliente %s", cod_cliente)
        wa.send_text(
            phone,
            "⚠️ Ocorreu um erro na consulta do PEKC.\n\nTente novamente em instantes.",
        )
        return {"status": "ok", "reason": "query_error"}

    message = _build_pekc_message(status, cod_cliente) + "\n\nEnvie outro código ou 0 para sair."

    try:
        wa.send_text(phone, message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao enviar mensagem para Evolution: %s", exc)
        raise HTTPException(status_code=500, detail="Falha ao enviar mensagem") from exc

    return {"status": "ok"}


def _extract_phone(payload: Dict[str, Any]) -> Optional[str]:
    data = payload.get("data", payload)
    key = data.get("key", {})

    remote_jid = key.get("remoteJid")
    remote_jid_alt = key.get("remoteJidAlt")
    participant = key.get("participant")
    sender_data = data.get("sender")
    sender_root = payload.get("sender")
    from_data = data.get("from")

    candidates = [
        remote_jid_alt,
        remote_jid if isinstance(remote_jid, str) and "@s.whatsapp.net" in remote_jid else None,
        participant,
        sender_data,
        sender_root,
        from_data,
        remote_jid,
    ]

    for source in candidates:
        digits = _normalize_phone(source or "")
        if _is_valid_phone_digits(digits):
            return digits

    return None


def _extract_text(payload: Dict[str, Any]) -> Optional[str]:
    data = payload.get("data", payload)
    message = data.get("message", {})

    candidates = [
        message.get("conversation"),
        message.get("extendedTextMessage", {}).get("text"),
        data.get("text"),
        payload.get("text"),
    ]

    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _is_group_message(payload: Dict[str, Any]) -> bool:
    data = payload.get("data", payload)
    remote_jid = data.get("key", {}).get("remoteJid", "")
    return isinstance(remote_jid, str) and remote_jid.endswith("@g.us")


def _is_from_me(payload: Dict[str, Any]) -> bool:
    data = payload.get("data", payload)
    return bool(data.get("key", {}).get("fromMe"))


def _normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _extract_client_code(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text)
    return digits or None


def _is_only_digits(text: str) -> bool:
    return bool(re.fullmatch(r"\d+", text.strip()))


def _is_valid_phone_digits(digits: str) -> bool:
    return bool(re.fullmatch(r"\d{10,15}", digits))


def _is_session_expired(state: Optional[Dict[str, datetime | str]]) -> bool:
    if not state:
        return False
    last_activity = state.get("last_activity")
    if not isinstance(last_activity, datetime):
        return True
    return datetime.now() - last_activity > timedelta(minutes=SESSION_TIMEOUT_MINUTES)


def _start_session(phone: str) -> None:
    states[phone] = {
        "state": "aguardando_codigo",
        "last_activity": datetime.now(),
    }


def _touch_session(phone: str) -> None:
    if phone in states:
        states[phone]["last_activity"] = datetime.now()


def _end_session(phone: str) -> None:
    states.pop(phone, None)


def _build_pekc_message(status: Optional[ClientPekcStatus], cod_cliente: str) -> str:
    if status is None:
        return (
            f"❌ Cliente {cod_cliente} não está na base do PEKC.\n\n"
            "Confira o código e tente novamente."
        )

    lines = [
        f"Cliente: {status.nome_cliente} ({status.cod_cliente})",
        "",
        f"✅ Itens positivados no PEKC: {status.itens_positivados}",
        f"📌 Itens faltantes: {status.itens_faltantes}",
    ]

    if status.produtos_faltantes:
        lines.extend(["", "Itens não positivados:"])
        lines.extend(f"- {cod} - {nome}" for cod, nome in status.produtos_faltantes)
    else:
        lines.extend(["", "🎉 Cliente com 100% dos itens PEKC positivados."])

    return "\n".join(lines)