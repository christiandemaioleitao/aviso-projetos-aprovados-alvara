"""
notificador.py
==============
Envia mensagens via Telegram Bot API.

Foco desta versão: uma única notificação concisa quando um projeto é
detectado como APROVADO. Sem IA, sem mensagens longas — só o essencial.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram limita uma mensagem a 4096 chars; deixamos folga.
MAX_MSG_LEN = 3800


def _is_dry_run() -> bool:
    """Lê a env DRY_RUN a cada chamada (permite ligar/desligar em runtime)."""
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────
def enviar_aprovacao(
    *,
    nome: str,
    projeto_id: int,
    url: str,
    numero_licenca: Optional[str],
    ultimo_andamento: dict,
    diffs: list[dict],
) -> bool:
    """
    Envia a notificação de aprovação. Retorna True se a mensagem foi
    efetivamente entregue (ou, em dry-run, "impressa").
    """
    mensagem = montar_mensagem_aprovacao(
        nome=nome,
        projeto_id=projeto_id,
        url=url,
        numero_licenca=numero_licenca,
        ultimo_andamento=ultimo_andamento,
        diffs=diffs,
    )
    return _send(mensagem)


def enviar_erro(nome: str, projeto_id: int, erro: str) -> None:
    """Notificação best-effort de erro de monitoramento."""
    msg = (
        f"⚠️ *AlvaráFácil — Erro*\n"
        f"Projeto: `{_escape(nome)}` \\(ID: {projeto_id}\\)\n"
        f"`{_escape(erro[:300])}`"
    )
    try:
        _send(msg, fail_silently=True)
    except Exception as e:
        logger.error("Falha ao enviar erro para Telegram: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Composição da mensagem
# ──────────────────────────────────────────────────────────────────────────────
def montar_mensagem_aprovacao(
    *,
    nome: str,
    projeto_id: int,
    url: str,
    numero_licenca: Optional[str],
    ultimo_andamento: dict,
    diffs: list[dict],
) -> str:
    """Monta o corpo MarkdownV2 (com fallback plaintext se o Telegram rejeitar)."""
    cabecalho = (
        f"✅ *PROJETO APROVADO* — AlvaráFácil\n"
        f"📋 `{_escape(nome)}` \\(ID: {projeto_id}\\)\n"
    )
    if numero_licenca:
        cabecalho += f"🔢 Licença: `{_escape(numero_licenca)}`\n"
    cabecalho += "─" * 24 + "\n"

    corpo_linhas: list[str] = []
    if ultimo_andamento:
        corpo_linhas.append(
            f"📅 *Último andamento* \\(seq {ultimo_andamento.get('sequencia', '?')}\\):"
        )
        corpo_linhas.append(
            f"  `{_escape(ultimo_andamento.get('data', ''))}`"
        )
        desc = (ultimo_andamento.get("descricao") or "").strip()
        if desc:
            # Trunca descrições muito longas para não estourar o limite do Telegram
            corpo_linhas.append(f"  > {_escape(desc[:500])}")
        if ultimo_andamento.get("situacao"):
            corpo_linhas.append(
                f"  • Situação: `{_escape(ultimo_andamento['situacao'])}`"
            )
        if ultimo_andamento.get("responsavel"):
            corpo_linhas.append(
                f"  • Resp.: `{_escape(ultimo_andamento['responsavel'])}`"
            )
        corpo_linhas.append("")

    # Resumo curto das demais mudanças detectadas
    extras = _resumir_diffs_extras(diffs, max_itens=3)
    if extras:
        corpo_linhas.append("📝 *Outras mudanças:*")
        corpo_linhas.extend(extras)
        corpo_linhas.append("")

    rodape = f"🔗 [Ver no AlvaráFácil]({url})"

    corpo = "\n".join(cabecalho.splitlines() + corpo_linhas) + "\n" + rodape
    # Truncamento defensivo
    if len(corpo) > MAX_MSG_LEN:
        corpo = corpo[: MAX_MSG_LEN - 50] + "\n…\\(truncado\\)"
    return corpo


def _resumir_diffs_extras(diffs: list[dict], max_itens: int = 3) -> list[str]:
    """Linhas de resumo de mudanças que não são o último andamento."""
    linhas: list[str] = []
    for d in diffs:
        t = d.get("tipo")
        if t == "situacao":
            linhas.append(f"  • Situação: `{_escape(d['anterior'])}` → `{_escape(d['atual'])}`")
        elif t == "andamentos_novos":
            for a in d["items"][:max_itens]:
                linhas.append(
                    f"  • Andamento #{_escape(a.get('sequencia', '?'))} "
                    f"\\({_escape(a.get('data', ''))}\\): "
                    f"{_escape((a.get('descricao') or '')[:80])}"
                )
        elif t == "andamento_status":
            linhas.append(
                f"  • Status do andamento: `{_escape(d['anterior'])}` → `{_escape(d['atual'])}`"
            )
        elif t == "anexos_novos":
            for a in d["items"][:max_itens]:
                linhas.append(
                    f"  • Anexo: `{_escape((a.get('nome') or '')[:60])}`"
                )
    return linhas[: max_itens * 3]


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────
def _send(text: str, *, fail_silently: bool = False) -> bool:
    if _is_dry_run():
        logger.info("[DRY-RUN] Mensagem que seria enviada:\n%s", text)
        return True

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        msg = "TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID não configurados"
        if fail_silently:
            logger.warning(msg)
            return False
        raise RuntimeError(msg)

    api_url = API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload_base = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    for attempt, parse_mode in enumerate(("MarkdownV2", ""), start=1):
        payload = {**payload_base, "parse_mode": parse_mode}
        try:
            resp = requests.post(api_url, json=payload, timeout=15)
        except requests.RequestException as e:
            if fail_silently:
                logger.error("Telegram: erro de rede (%s)", e)
                return False
            raise

        if resp.ok:
            logger.info("Telegram: mensagem enviada (status %s, parse_mode=%r)",
                        resp.status_code, parse_mode)
            return True

        # MarkdownV2 falhou por causa de formatação — tenta plaintext
        if parse_mode == "MarkdownV2" and resp.status_code == 400:
            logger.warning("Telegram rejeitou MarkdownV2 (400), tentando sem formatação")
            continue

        body = (resp.text or "")[:200]
        logger.error("Telegram: HTTP %s — %s", resp.status_code, body)
        if fail_silently:
            return False
        resp.raise_for_status()

    return False


def _escape(text: str) -> str:
    """Escapa caracteres especiais do MarkdownV2 do Telegram."""
    special = set(r"\_*[]()~`>#+-=|{}.!")
    return "".join(f"\\{c}" if c in special else c for c in str(text))
