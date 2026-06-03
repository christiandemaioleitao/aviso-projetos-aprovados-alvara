"""Testes do scraper (parsing de HTML estático, sem rede)."""

from src.scraper import _parse_andamentos, _parse_anexos, _pagina_de_erro
from bs4 import BeautifulSoup


HTML_ANDAMENTOS = """
<table>
  <thead>
    <tr>
      <th>Sequência</th>
      <th>Data</th>
      <th>Descrição</th>
      <th>Situação</th>
      <th>Responsável</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>2</td><td>11/05/2024 21:48</td>
      <td>Taxa do projeto gerada e solicitação encerrada.</td>
      <td>Fechada</td><td>VALFRAN</td>
    </tr>
    <tr>
      <td>1</td><td>10/05/2024 14:38</td>
      <td>Solicitação recebida</td><td>Em Execução</td><td>VALFRAN</td>
    </tr>
  </tbody>
</table>
"""

HTML_ANEXOS = """
<table>
  <thead>
    <tr>
      <th>Ícone</th>
      <th>Nome Arquivo</th>
      <th>Descrição</th>
      <th>Data</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>📎</td>
      <td>laudo.pdf</td>
      <td>Laudo de aprovação</td>
      <td>09/05/2024</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_andamentos_cabecalho_com_sequencia_e_descricao():
    soup = BeautifulSoup(HTML_ANDAMENTOS, "lxml")
    rows = _parse_andamentos(soup)
    assert len(rows) == 2
    assert rows[0]["sequencia"] == "2"
    assert "Taxa do projeto gerada" in rows[0]["descricao"]
    assert rows[0]["situacao"] == "Fechada"
    assert rows[0]["responsavel"] == "VALFRAN"


def test_parse_andamentos_sem_tabela():
    soup = BeautifulSoup("<html><body>sem tabela</body></html>", "lxml")
    assert _parse_andamentos(soup) == []


def test_parse_anexos():
    soup = BeautifulSoup(HTML_ANEXOS, "lxml")
    rows = _parse_anexos(soup)
    assert len(rows) == 1
    assert rows[0]["nome"] == "laudo.pdf"
    assert rows[0]["descricao"] == "Laudo de aprovação"
    assert rows[0]["data"] == "09/05/2024"


def test_pagina_de_erro_detecta_404():
    assert _pagina_de_erro("404 - File or directory not found.") is True


def test_pagina_de_erro_pagina_normal():
    assert _pagina_de_erro("<html>OK</html>") is False
