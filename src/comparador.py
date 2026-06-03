"""
comparador.py
=============
Compara dois snapshots (anterior × atual) de um projeto e devolve as diferenças
encontradas. Foco: detectar QUALQUER mudança relevante — não só mudanças
relacionadas a aprovação.

Usado pelo main.py para decidir se deve notificar (e para mostrar contexto
no log e na mensagem do Telegram).
"""

from __future__ import annotations

from typing import Any


def comparar(anterior: dict, atual: dict) -> list[dict]:
    """
    Devolve uma lista de diffs (vazia = sem mudanças).
    Cada diff é um dict com pelo menos a chave "tipo" e dados específicos.
    """
    diffs: list[dict] = []

    # 1. Mudança na Situação geral
    if (anterior.get("situacao") or "") != (atual.get("situacao") or ""):
        diffs.append({
            "tipo": "situacao",
            "label": "Situação do Projeto",
            "anterior": anterior.get("situacao") or "—",
            "atual": atual.get("situacao") or "—",
        })

    # 2. Novos andamentos (comparando por sequência)
    seqs_ant = {a.get("sequencia") for a in anterior.get("andamentos", [])}
    novos = [a for a in atual.get("andamentos", []) if a.get("sequencia") not in seqs_ant]
    if novos:
        diffs.append({
            "tipo": "andamentos_novos",
            "label": "Novos Andamentos",
            "items": novos,
        })

    # 3. Mudança de situação em andamentos existentes
    map_ant = {a.get("sequencia"): a for a in anterior.get("andamentos", [])}
    for a_atual in atual.get("andamentos", []):
        seq = a_atual.get("sequencia")
        a_ant = map_ant.get(seq)
        if a_ant and (a_ant.get("situacao") or "") != (a_atual.get("situacao") or ""):
            diffs.append({
                "tipo": "andamento_status",
                "label": f"Andamento #{seq} ({a_atual.get('data', '')})",
                "anterior": a_ant.get("situacao", "—"),
                "atual": a_atual.get("situacao", "—"),
                "descricao": a_atual.get("descricao", ""),
            })

    # 4. Novos anexos
    nomes_ant = {a.get("nome") for a in anterior.get("anexos", [])}
    novos_anexos = [a for a in atual.get("anexos", []) if a.get("nome") not in nomes_ant]
    if novos_anexos:
        diffs.append({
            "tipo": "anexos_novos",
            "label": "Novos Documentos Anexados",
            "items": novos_anexos,
        })

    return diffs


def houve_mudanca(anterior: dict, atual: dict) -> bool:
    """Atalho: True se há qualquer diff relevante."""
    return len(comparar(anterior, atual)) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Formatação para log
# ──────────────────────────────────────────────────────────────────────────────
def formatar_diffs_resumido(diffs: list[dict]) -> str:
    """Linha única para log — útil quando há muitos diffs."""
    partes: list[str] = []
    for d in diffs:
        t = d.get("tipo")
        if t == "situacao":
            partes.append(f"situação: {d['anterior']} → {d['atual']}")
        elif t == "andamentos_novos":
            partes.append(f"{len(d['items'])} andamento(s) novo(s)")
        elif t == "andamento_status":
            partes.append(f"#{d['label']}: {d['anterior']} → {d['atual']}")
        elif t == "anexos_novos":
            partes.append(f"{len(d['items'])} anexo(s) novo(s)")
    return "; ".join(partes) or "(sem mudanças)"
