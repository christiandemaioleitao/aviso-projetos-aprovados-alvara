"""Script de validação manual — testa o detector com os dados reais salvos."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.detector import is_approved, resumo_aprovacao  # noqa


def main() -> int:
    ids = [19474, 46753, 45753, 47847]
    falhas = 0

    for pid in ids:
        path = ROOT / "data" / f"{pid}.json"
        if not path.exists():
            print(f"--- ID {pid} --- (sem dados salvos, pulando)")
            continue
        with path.open(encoding="utf-8") as f:
            state = json.load(f)
        resumo = resumo_aprovacao(state)
        aprovado = resumo["aprovado"]
        motivo = resumo["motivo"]
        seq = (resumo["ultimo_andamento"] or {}).get("sequencia")
        data = (resumo["ultimo_andamento"] or {}).get("data")
        desc = (resumo["ultimo_andamento"] or {}).get("descricao") or ""
        desc = desc[:120]

        # Esperado: 19474 e 46753 = APROVADO; 45753 e 47847 = PENDENTE
        esperado = pid in (19474, 46753)
        status = "OK" if aprovado == esperado else "FALHOU"
        if aprovado != esperado:
            falhas += 1

        print(f"--- ID {pid} --- [{status}]")
        print(f"  esperado aprovado?  {esperado}")
        print(f"  detectado aprovado? {aprovado}")
        print(f"  motivo:             {motivo}")
        print(f"  último seq:         {seq}")
        print(f"  último data:        {data}")
        print(f"  último desc:        {desc}")
        print()

    if falhas:
        print(f"[FALHA] {falhas} caso(s) falharam.")
        return 1
    print("[OK] Todos os 4 casos bateram com o esperado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
