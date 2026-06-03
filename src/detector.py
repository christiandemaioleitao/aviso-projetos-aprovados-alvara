"""
detector.py
===========
Decide se um projeto está APROVADO com base no conteúdo da página.

Regra (definida pelo usuário):
    Um projeto é considerado APROVADO quando o **último andamento** (o mais
    recente — primeiro item da lista) contém uma das expressões abaixo na
    descrição, ignorando capitalização e acentuação:

        - "taxa do projeto gerada"
        - "emissão de taxa final"

Qualquer outro caso (incluindo lista de andamentos vazia) é considerado
PENDENTE — esses são silenciosamente ignorados (sem notificação no Telegram).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Padrões de aprovação
# ──────────────────────────────────────────────────────────────────────────────
# Lista explícita (não regex) para deixar fácil auditar/ajustar.
# A normalização (sem acentos / lowercase) acontece em _normalize().
APPROVAL_KEYWORDS: tuple[str, ...] = (
    "taxa do projeto gerada",
    "emissao de taxa final",          # "emissão de taxa final" sem acento
)


def _normalize(text: str) -> str:
    """Lowercase + remove acentos. Ex.: 'Documentação' -> 'documentacao'."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _keywords_normalizados(keywords: Iterable[str] = APPROVAL_KEYWORDS) -> list[str]:
    return [_normalize(k) for k in keywords]


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────
def is_approved(state: dict) -> bool:
    """
    Recebe o dict de um ProjectState.to_dict() e devolve True se o último
    andamento contém uma das expressões de aprovação.
    """
    ultimo = _get_ultimo_andamento(state)
    if not ultimo:
        return False
    descricao = ultimo.get("descricao", "") or ""
    desc_norm = _normalize(descricao)
    if not desc_norm:
        return False
    return any(kw in desc_norm for kw in _keywords_normalizados())


def approval_reason(state: dict) -> Optional[str]:
    """
    Devolve a frase/trecho da descrição do último andamento que contém uma
    palavra-chave de aprovação. Útil para a mensagem do Telegram.
    Devolve None se não aprovado.
    """
    ultimo = _get_ultimo_andamento(state)
    if not ultimo:
        return None
    descricao = (ultimo.get("descricao") or "").strip()
    if not descricao:
        return None
    desc_norm = _normalize(descricao)
    for kw in _keywords_normalizados():
        idx = desc_norm.find(kw)
        if idx >= 0:
            # Devolve o trecho original (com acentos) onde o match foi encontrado.
            # Mapeamos o índice normalizado de volta pro texto original.
            return _slice_original(descricao, desc_norm, idx, len(kw))
    return None


def _get_ultimo_andamento(state: dict) -> Optional[dict]:
    """
    Retorna o andamento mais recente.
    O scraper entrega a lista ordenada do mais novo (sequência maior) para o
    mais antigo — andamentos[0] é o último.
    """
    andamentos = state.get("andamentos") or []
    if not andamentos:
        return None
    return andamentos[0]


def _slice_original(original: str, normalized: str, start_norm: int, length: int) -> str:
    """
    A normalização remove caracteres (acentos viram espaços), então o índice
    na string normalizada não bate 1:1 com a original. Esta função reconstrói
    o trecho correspondente na string original.
    """
    # Mapeia caractere da string normalizada -> caractere da original.
    # Quando a normalização "consome" um caractere (acento), pulamos 1 na original.
    i_orig = 0
    i_norm = 0
    while i_norm < start_norm and i_orig < len(original):
        if _normalize(original[i_orig]) == "":
            i_orig += 1
            continue
        if _normalize(original[i_orig])[0] == normalized[i_norm]:
            i_orig += 1
            i_norm += 1
        else:
            i_orig += 1
    end_orig = i_orig
    consumed = 0
    while consumed < length and end_orig < len(original):
        if _normalize(original[end_orig]) == "":
            end_orig += 1
            continue
        consumed += 1
        end_orig += 1
    return original[i_orig:end_orig]


# ──────────────────────────────────────────────────────────────────────────────
# Utilitário extra — útil em testes e logs
# ──────────────────────────────────────────────────────────────────────────────
def resumo_aprovacao(state: dict) -> dict:
    """
    Devolve um pequeno resumo usado em logs e mensagens.
    """
    ultimo = _get_ultimo_andamento(state)
    return {
        "aprovado": is_approved(state),
        "ultimo_andamento": {
            "sequencia": (ultimo or {}).get("sequencia"),
            "data": (ultimo or {}).get("data"),
            "descricao": (ultimo or {}).get("descricao"),
        },
        "motivo": approval_reason(state),
    }
