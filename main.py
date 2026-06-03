"""
main.py
=======
Ponto de entrada do monitor AlvaráFácil.

Fluxo (refatorado):
  1. Lê a lista de projetos de `projetos.json`.
  2. Para cada projeto (em paralelo), busca o estado atual via scraping.
  3. Compara com o snapshot salvo em `data/{id}.json`.
  4. Se NÃO houve mudança → segue para o próximo projeto (sem notificar).
  5. Se houve mudança:
       a. Salva o novo snapshot em `data/{id}.json`.
       b. Verifica se o projeto foi APROVADO (último andamento contém
          "Taxa do projeto gerada" ou "emissão de taxa final").
       c. Se aprovado → notifica no Telegram.
       d. Se pendente → ignora (silencioso, sem notificação).
  6. Encerra com um resumo consolidado (logs + retorno).

Execução:
  - Modo normal:  `python main.py`
  - Dry-run (não envia Telegram):  `DRY_RUN=1 python main.py`
  - Filtrar projetos:  `ONLY_IDS=19474,47847 python main.py`
  - Forçar refetch (mesmo sem mudança):  `FORCE=1 python main.py`
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Garante que `src` está no path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.scraper import (  # noqa: E402
    ProjectState,
    _build_session,
    fetch_project,
    normalizar_id,
)
from src.comparador import comparar, formatar_diffs_resumido  # noqa: E402
from src.detector import is_approved, resumo_aprovacao  # noqa: E402
from src.notificador import enviar_aprovacao, enviar_erro  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Configuração / logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alvarafacil-monitor")

DATA_DIR = BASE_DIR / "data"
PROJETOS_FILE = BASE_DIR / "projetos.json"

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "6"))     # paralelismo seguro p/ GitHub Actions
FETCH_TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", "30"))


# ──────────────────────────────────────────────────────────────────────────────
# Persistência
# ──────────────────────────────────────────────────────────────────────────────
def load_estado(projeto_id: int) -> Optional[dict]:
    path = DATA_DIR / f"{projeto_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("Estado de %s corrompido (%s) — ignorando.", projeto_id, e)
        return None


def save_estado(state: ProjectState) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = state.to_dict()
    payload["_salvo_em"] = datetime.now(timezone.utc).isoformat()
    path = DATA_DIR / f"{state.projeto_id}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Estado salvo em %s", path)


# ──────────────────────────────────────────────────────────────────────────────
# Carregamento da lista de projetos
# ──────────────────────────────────────────────────────────────────────────────
def carregar_projetos() -> list[dict]:
    if not PROJETOS_FILE.exists():
        raise FileNotFoundError(f"projetos.json não encontrado em {PROJETOS_FILE}")

    try:
        projetos = json.loads(PROJETOS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"projetos.json inválido: {e}") from e

    if not isinstance(projetos, list):
        raise ValueError("projetos.json deve conter uma lista no nível raiz")

    # Validação mínima
    for p in projetos:
        if "id" not in p:
            raise ValueError(f"Projeto sem campo 'id': {p}")

    # Filtro opcional via env ONLY_IDS
    only = os.environ.get("ONLY_IDS", "").strip()
    if only:
        wanted = {normalizar_id(x) for x in only.split(",") if x.strip()}
        wanted.discard(None)
        antes = len(projetos)
        projetos = [p for p in projetos if normalizar_id(p.get("id")) in wanted]
        logger.info("Filtro ONLY_IDS=%s — %d/%d projetos", sorted(wanted), len(projetos), antes)

    return projetos


# ──────────────────────────────────────────────────────────────────────────────
# Processamento de UM projeto
# ──────────────────────────────────────────────────────────────────────────────
def processar_projeto(projeto: dict, session) -> dict:
    """
    Processa um projeto. Retorna um dict com o resultado p/ agregação.
    Nunca lança exceção (erros viram campos no resultado).
    """
    pid = normalizar_id(projeto.get("id"))
    tipo = projeto.get("tipo_alvara", 2)
    nome = projeto.get("nome") or f"Projeto {pid}"

    resultado = {
        "id": pid,
        "nome": nome,
        "status": "ok",          # ok | erro | sem_mudanca | mudanca_pendente | aprovado
        "mudou": False,
        "aprovado": False,
        "andamentos": 0,
        "erro": None,
        "url": f"https://www10.goiania.go.gov.br/alvarafacil/AcompanhaAprovacaoProjeto.aspx?ProjetoId={pid}&TipoAlvara={tipo}",
    }

    if pid is None:
        resultado["status"] = "erro"
        resultado["erro"] = "id inválido"
        return resultado

    logger.info("── %s (ID %s) ──", nome, pid)
    t0 = time.time()

    # 1. Fetch
    try:
        state = fetch_project(pid, tipo, session=session, timeout=FETCH_TIMEOUT)
    except Exception as e:
        msg = str(e)
        logger.error("Falha no scraping: %s", msg)
        resultado.update({"status": "erro", "erro": msg})
        try:
            enviar_erro(nome, pid, msg)
        except Exception:
            pass
        return resultado

    elapsed = time.time() - t0
    resultado["andamentos"] = len(state.andamentos)
    logger.info(
        "Coletado em %.1fs — situação=%s, andamentos=%d, anexos=%d",
        elapsed, state.situacao, len(state.andamentos), len(state.anexos),
    )

    # 2. Carrega estado anterior
    anterior = load_estado(pid)
    force = os.environ.get("FORCE", "").lower() in ("1", "true", "yes")

    if anterior is None:
        logger.info("Primeiro registro — salvando estado inicial (sem notificação).")
        state.fetched_at = datetime.now(timezone.utc).isoformat()
        save_estado(state)
        resultado.update({"status": "primeiro_registro", "mudou": True})
        return resultado

    # 3. Compara
    diffs = comparar(anterior, state.to_dict())
    if not diffs:
        logger.info("Sem mudanças — projeto %s.", pid)
        resultado["status"] = "sem_mudanca"
        return resultado

    if not force:
        logger.info("Mudanças detectadas: %d — %s", len(diffs), formatar_diffs_resumido(diffs))

    # 4. Salva novo estado SEMPRE que há mudança
    state.fetched_at = datetime.now(timezone.utc).isoformat()
    save_estado(state)
    resultado["mudou"] = True

    # 5. Avalia aprovação
    snapshot = state.to_dict()
    info = resumo_aprovacao(snapshot)
    resultado["aprovado"] = info["aprovado"]
    logger.info("Aprovado? %s — último andamento: seq=%s, data=%s",
                info["aprovado"],
                info["ultimo_andamento"]["sequencia"],
                info["ultimo_andamento"]["data"])

    if not info["aprovado"]:
        logger.info("Projeto %s mudou mas segue PENDENTE — sem notificação.", pid)
        resultado["status"] = "mudanca_pendente"
        return resultado

    # 6. Notifica no Telegram
    try:
        ok = enviar_aprovacao(
            nome=nome,
            projeto_id=pid,
            url=state.url,
            numero_licenca=state.numero_licenca,
            ultimo_andamento=info["ultimo_andamento"],
            diffs=diffs,
        )
        if ok:
            logger.info("Notificação enviada ao Telegram para %s.", pid)
            resultado["status"] = "aprovado"
        else:
            logger.warning("Notificação NÃO enviada (verifique TELEGRAM_*).")
            resultado["status"] = "aprovado_sem_notificacao"
    except Exception as e:
        logger.error("Falha ao enviar Telegram: %s", e)
        resultado["status"] = "aprovado_erro_notificacao"
        resultado["erro"] = f"notificação: {e}"

    return resultado


# ──────────────────────────────────────────────────────────────────────────────
# Loop principal
# ──────────────────────────────────────────────────────────────────────────────
def run(projetos: list[dict]) -> dict:
    logger.info("═══ AlvaráFácil Monitor ═══")
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    logger.info("Projetos: %d · workers=%d · dry_run=%s", len(projetos), MAX_WORKERS, dry)

    session = _build_session()
    agregador = {
        "total": len(projetos),
        "aprovados": 0,
        "mudancas_pendentes": 0,
        "sem_mudanca": 0,
        "primeiro_registro": 0,
        "erros": 0,
    }
    resultados: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(processar_projeto, p, session): p for p in projetos
        }
        for fut in as_completed(futures):
            r = fut.result()
            resultados.append(r)
            s = r["status"]
            if s == "aprovado" or s == "aprovado_sem_notificacao":
                agregador["aprovados"] += 1
            elif s == "mudanca_pendente":
                agregador["mudancas_pendentes"] += 1
            elif s == "sem_mudanca":
                agregador["sem_mudanca"] += 1
            elif s == "primeiro_registro":
                agregador["primeiro_registro"] += 1
            elif s == "erro":
                agregador["erros"] += 1

    logger.info("═══ Resumo ═══")
    logger.info("Total: %d · Aprovados: %d · Pendentes: %d · Sem mudança: %d · "
                "1º registro: %d · Erros: %d",
                agregador["total"], agregador["aprovados"],
                agregador["mudancas_pendentes"], agregador["sem_mudanca"],
                agregador["primeiro_registro"], agregador["erros"])
    return {"agregador": agregador, "resultados": resultados}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AlvaráFácil Monitor")
    p.add_argument("--only", help="Lista de IDs separados por vírgula (filtra projetos.json)")
    p.add_argument("--dry-run", action="store_true", help="Não envia Telegram")
    p.add_argument("--force", action="store_true", help="Trata sempre como mudança")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.only:
        os.environ["ONLY_IDS"] = args.only
    if args.dry_run:
        os.environ["DRY_RUN"] = "1"
    if args.force:
        os.environ["FORCE"] = "1"

    try:
        projetos = carregar_projetos()
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        return 2

    if not projetos:
        logger.warning("Nenhum projeto a verificar (após filtros).")
        return 0

    try:
        run(projetos)
    except Exception as e:
        logger.exception("Erro inesperado: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
