"""
scraper.py
==========
Busca e extrai dados estruturados do AlvaráFácil da Prefeitura de Goiânia.

Responsabilidades:
  - Baixar a página HTML de um projeto via requests com retries.
  - Extrair a "Situação" geral do projeto (Pendente / Publicado / Em Execução / etc).
  - Extrair a tabela de Andamentos (histórico do processo).
  - Extrair a tabela de Anexos (documentos juntados pelo analista).
  - Retornar um dict estruturado que pode ser serializado em JSON e comparado
    com snapshots anteriores.

Notas:
  - A página usa ASP.NET WebForms (OutSystems) com vários campos de formulário.
  - Caracteres acentuados chegam como entidades HTML (ex.: &#231; = "ç"); o
    BeautifulSoup resolve isso automaticamente.
  - A lista de andamentos vem ordenada do mais recente (sequência maior) para o
    mais antigo. O detector de aprovação sempre olha andamentos[0].
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www10.goiania.go.gov.br/alvarafacil/AcompanhaAprovacaoProjeto.aspx"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Timeout de leitura. Em conexões ruins da SEPLAN, 30s é o limite prático.
DEFAULT_TIMEOUT = 30


# ──────────────────────────────────────────────────────────────────────────────
# Sessão HTTP com retry automático
# ──────────────────────────────────────────────────────────────────────────────
def _build_session() -> requests.Session:
    """Cria uma requests.Session com retry exponencial e backoff."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,             # 0s, 1.5s, 3s, 4.5s...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(DEFAULT_HEADERS)
    return session


# ──────────────────────────────────────────────────────────────────────────────
# Estrutura de retorno
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ProjectState:
    """Snapshot estruturado de um projeto. Pronto pra serializar em JSON."""

    projeto_id: int
    tipo_alvara: int
    url: str
    situacao: Optional[str] = None
    numero_licenca: Optional[str] = None
    tipo: Optional[str] = None
    autor: Optional[str] = None
    andamentos: list[dict] = field(default_factory=list)
    anexos: list[dict] = field(default_factory=list)
    fetched_at: str = ""               # preenchido pelo main

    def to_dict(self) -> dict:
        return {
            "projeto_id": self.projeto_id,
            "tipo_alvara": self.tipo_alvara,
            "url": self.url,
            "situacao": self.situacao,
            "numero_licenca": self.numero_licenca,
            "tipo": self.tipo,
            "autor": self.autor,
            "andamentos": self.andamentos,
            "anexos": self.anexos,
        }


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────
def fetch_project(
    project_id: int,
    tipo_alvara: int = 2,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> ProjectState:
    """
    Busca e parseia os dados de um projeto no AlvaráFácil.
    Retorna um ProjectState; levanta RuntimeError em caso de falha de rede/HTTP.
    """
    url = f"{BASE_URL}?ProjetoId={project_id}&TipoAlvara={tipo_alvara}"
    sess = session or _build_session()

    try:
        resp = sess.get(url, timeout=timeout)
    except requests.Timeout as e:
        raise RuntimeError(f"Timeout ({timeout}s) ao buscar projeto {project_id}") from e
    except requests.RequestException as e:
        raise RuntimeError(f"Erro de rede ao buscar projeto {project_id}: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(
            f"HTTP {resp.status_code} ao buscar projeto {project_id} "
            f"({url})"
        )

    # Página de erro do OutSystems (ex.: 404 do ASP.NET) — quando o ID não existe,
    # o servidor ainda devolve 200, mas com markup de erro.
    if _pagina_de_erro(resp.text):
        raise RuntimeError(f"Página de erro retornada para projeto {project_id}")

    soup = BeautifulSoup(resp.text, "lxml")
    return _parse_page(soup, project_id, tipo_alvara, url)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de parsing
# ──────────────────────────────────────────────────────────────────────────────
_ERRO_PATTERNS = (
    "404 - File or directory not found",
    "erro inesperado",
    "página não encontrada",
    "Object reference not set",
)


def _pagina_de_erro(html: str) -> bool:
    lowered = html.lower()
    return any(p.lower() in lowered for p in _ERRO_PATTERNS)


def _extract_text_after_label(lines: list[str], label: str) -> Optional[str]:
    """
    Retorna o primeiro valor não-vazio que aparece na linha seguinte a um label.
    Ignora valores que pareçam ser outros labels (terminam em ':').
    """
    for i, line in enumerate(lines):
        if line.strip() == label and i + 1 < len(lines):
            val = lines[i + 1].strip()
            if val and not val.endswith(":"):
                return val
    return None


def _parse_page(soup: BeautifulSoup, project_id: int, tipo_alvara: int, url: str) -> ProjectState:
    """Extrai os campos relevantes do HTML parseado."""
    raw_text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    return ProjectState(
        projeto_id=project_id,
        tipo_alvara=tipo_alvara,
        url=url,
        situacao=_extract_text_after_label(lines, "Situação"),
        numero_licenca=_extract_text_after_label(lines, "Licença Prévia"),
        tipo=_extract_text_after_label(lines, "Tipo"),
        autor=_extract_text_after_label(lines, "Autor"),
        andamentos=_parse_andamentos(soup),
        anexos=_parse_anexos(soup),
    )


def _parse_andamentos(soup: BeautifulSoup) -> list[dict]:
    """
    Extrai as linhas da tabela de Andamentos.
    Estrutura típica: Sequência | Data | Descrição | Situação | Responsável
    """
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if "Sequência" not in headers and "Sequencia" not in headers:
            continue
        if "Descrição" not in headers and "Descricao" not in headers:
            continue

        rows: list[dict] = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 4 or not cells[0].isdigit():
                continue
            rows.append({
                "sequencia": cells[0],
                "data": cells[1] if len(cells) > 1 else "",
                "descricao": cells[2] if len(cells) > 2 else "",
                "situacao": cells[3] if len(cells) > 3 else "",
                "responsavel": cells[4] if len(cells) > 4 else "",
            })
        return rows
    return []


def _parse_anexos(soup: BeautifulSoup) -> list[dict]:
    """
    Extrai as linhas da tabela de Anexos do analista.
    Estrutura típica: [ícone] | Nome Arquivo | Descrição | Data
    """
    for table in soup.find_all("table"):
        headers_text = " ".join(th.get_text(strip=True) for th in table.find_all("th"))
        if "Nome Arquivo" not in headers_text:
            continue
        if "Data" not in headers_text:
            continue

        rows: list[dict] = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 3:
                continue
            # Geralmente: [0] = ícone, [1] = nome, [2] = descrição, [3] = data
            nome = cells[1] if len(cells) > 1 else ""
            desc = cells[2] if len(cells) > 2 else ""
            data = cells[3] if len(cells) > 3 else ""
            if nome:
                rows.append({"nome": nome, "descricao": desc, "data": data})
        return rows
    return []


# ──────────────────────────────────────────────────────────────────────────────
# Utilitário: normalização de ID
# ──────────────────────────────────────────────────────────────────────────────
def normalizar_id(valor) -> Optional[int]:
    """Aceita '19474', 19474, '19.474' e devolve 19474 (ou None)."""
    if valor is None:
        return None
    if isinstance(valor, int):
        return valor
    s = re.sub(r"\D", "", str(valor))
    return int(s) if s else None
