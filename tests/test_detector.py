"""
Testes do detector de aprovação.
Roda offline — sem scraping de verdade.
"""

from src.detector import (
    APPROVAL_KEYWORDS,
    _normalize,
    approval_reason,
    is_approved,
    resumo_aprovacao,
)


# ─── Casos aprovados ─────────────────────────────────────────────────────────
def test_aprovado_taxa_do_projeto_gerada():
    state = {
        "andamentos": [
            {
                "sequencia": "38",
                "data": "11/05/2024 21:48:01",
                "descricao": (
                    "Taxa do projeto gerada e solicitação encerrada. "
                    "Motivo: Conforme documentação anexada e análise realizada, "
                    "encaminhamos para liberação de taxa."
                ),
                "situacao": "Fechada",
                "responsavel": "VALFRAN",
            }
        ]
    }
    assert is_approved(state) is True


def test_aprovado_emissao_taxa_final():
    state = {
        "andamentos": [
            {
                "sequencia": "1",
                "data": "02/06/2026 10:00:00",
                "descricao": (
                    "Documentação e projeto deferidos, apto à emissão de taxa final."
                ),
                "situacao": "Fechada",
            }
        ]
    }
    assert is_approved(state) is True


def test_aprovado_com_acentos_e_maiusculas():
    state = {
        "andamentos": [
            {
                "sequencia": "1",
                "data": "x",
                "descricao": "TAXA DO PROJETO GERADA e SOLICITAÇÃO ENCERRADA.",
            }
        ]
    }
    assert is_approved(state) is True


# ─── Casos pendentes ─────────────────────────────────────────────────────────
def test_pendente_descricao_generica():
    state = {
        "andamentos": [
            {
                "sequencia": "10",
                "data": "20/05/2026",
                "descricao": "Análise do projeto encontrou inconsistências. Encaminhada para o contribuinte.",
                "situacao": "Aguardando",
            }
        ]
    }
    assert is_approved(state) is False


def test_pendente_solicitacao_recebida():
    state = {
        "andamentos": [
            {"sequencia": "2", "data": "x", "descricao": "Solicitação recebida"},
        ]
    }
    assert is_approved(state) is False


def test_pendente_reencaminhado():
    state = {
        "andamentos": [
            {
                "sequencia": "1",
                "data": "x",
                "descricao": "Reencaminhado pelo contribuinte para nova análise.",
            }
        ]
    }
    assert is_approved(state) is False


def test_pendente_andamento_mais_antigo_e_aprovado_mas_ultimo_nao():
    """
    A regra é: o ÚLTIMO andamento é o que vale. Se o último não bate,
    mesmo que algum andamento anterior tenha 'Taxa do projeto gerada',
    o projeto não é considerado aprovado pelo detector.
    """
    state = {
        "andamentos": [
            # mais recente (lista vem ordenada do mais novo para o mais antigo)
            {"sequencia": "5", "data": "x", "descricao": "Solicitação recebida"},
            # antigo — foi aprovado, mas foi reaberto? não importa, regra é o último.
            {"sequencia": "4", "data": "x", "descricao": "Taxa do projeto gerada"},
        ]
    }
    assert is_approved(state) is False


# ─── Edge cases ──────────────────────────────────────────────────────────────
def test_vazio():
    assert is_approved({"andamentos": []}) is False


def test_sem_andamentos():
    assert is_approved({}) is False


def test_descricao_vazia():
    state = {"andamentos": [{"sequencia": "1", "data": "x", "descricao": ""}]}
    assert is_approved(state) is False


def test_normalize_remove_acentos():
    assert _normalize("Documentação") == "documentacao"
    assert _normalize("Análise") == "analise"
    assert _normalize("ÀÁÂÃÄÅ") == "aaaaaa"


def test_approval_reason_devolve_match():
    state = {
        "andamentos": [
            {
                "sequencia": "1",
                "data": "x",
                "descricao": (
                    "Taxa do projeto gerada e solicitação encerrada. "
                    "Motivo: Documentação e projeto deferidos, apto à emissão de taxa final."
                ),
            }
        ]
    }
    reason = approval_reason(state)
    assert reason is not None
    assert "Taxa" in reason or "taxa" in reason.lower()


def test_approval_reason_none_quando_pendente():
    state = {"andamentos": [{"sequencia": "1", "data": "x", "descricao": "Solicitação recebida"}]}
    assert approval_reason(state) is None


def test_resumo_aprovacao():
    state = {
        "andamentos": [
            {
                "sequencia": "38",
                "data": "11/05/2024",
                "descricao": "Taxa do projeto gerada. Motivo: x.",
            }
        ]
    }
    r = resumo_aprovacao(state)
    assert r["aprovado"] is True
    assert r["ultimo_andamento"]["sequencia"] == "38"
    assert r["motivo"] is not None
