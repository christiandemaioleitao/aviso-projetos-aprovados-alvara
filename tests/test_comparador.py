"""Testes do comparador (sem rede)."""

from src.comparador import comparar, houve_mudanca, formatar_diffs_resumido


def _state(andamentos=(), anexos=(), situacao="Pendente"):
    return {
        "situacao": situacao,
        "andamentos": list(andamentos),
        "anexos": list(anexos),
    }


def test_sem_mudancas():
    s = _state(
        andamentos=[{"sequencia": "1", "data": "x", "descricao": "A", "situacao": "OK"}],
        anexos=[{"nome": "f.pdf", "descricao": "d", "data": "x"}],
    )
    assert comparar(s, s) == []
    assert houve_mudanca(s, s) is False


def test_mudanca_situacao():
    a = _state(situacao="Pendente")
    b = _state(situacao="Publicado")
    diffs = comparar(a, b)
    assert any(d["tipo"] == "situacao" for d in diffs)


def test_novo_andamento():
    a = _state(andamentos=[{"sequencia": "1", "data": "x", "descricao": "A", "situacao": "OK"}])
    b = _state(andamentos=[
        {"sequencia": "1", "data": "x", "descricao": "A", "situacao": "OK"},
        {"sequencia": "2", "data": "y", "descricao": "B", "situacao": "Nova"},
    ])
    diffs = comparar(a, b)
    tipos = {d["tipo"] for d in diffs}
    assert "andamentos_novos" in tipos


def test_andamento_status_mudou():
    a = _state(andamentos=[{"sequencia": "1", "data": "x", "descricao": "A", "situacao": "OK"}])
    b = _state(andamentos=[{"sequencia": "1", "data": "x", "descricao": "A", "situacao": "Fechada"}])
    diffs = comparar(a, b)
    assert any(d["tipo"] == "andamento_status" for d in diffs)


def test_novo_anexo():
    a = _state(anexos=[{"nome": "a.pdf", "descricao": "x", "data": "01/01"}])
    b = _state(anexos=[
        {"nome": "a.pdf", "descricao": "x", "data": "01/01"},
        {"nome": "b.pdf", "descricao": "y", "data": "02/01"},
    ])
    diffs = comparar(a, b)
    assert any(d["tipo"] == "anexos_novos" for d in diffs)


def test_formatar_resumido_nao_explode():
    a = _state()
    b = _state(
        situacao="Publicado",
        andamentos=[{"sequencia": "5", "data": "x", "descricao": "Y", "situacao": "Fechada"}],
    )
    diffs = comparar(a, b)
    txt = formatar_diffs_resumido(diffs)
    assert isinstance(txt, str) and txt
