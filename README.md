# AlvaráFácil Monitor

Monitor de projetos de aprovação de alvará da Prefeitura de Goiânia (AlvaráFácil). Roda diariamente, identifica se o projeto foi **aprovado** e avisa no Telegram.

> **O que mudou nesta refatoração (v2):**
> - Removida a dependência da OpenRouter/IA — a aprovação é detectada por **regra determinística** (palavras-chave no último andamento).
> - Pipeline linear: scraping → diff → detector de aprovação → Telegram (se aprovado). Sem chamada de LLM, sem fallback de texto.
> - Paralelismo (`ThreadPoolExecutor`) — checagem dos N projetos em paralelo.
> - Retry exponencial e session HTTP reaproveitada.
> - **Pendentes não notificam.** Silenciosamente ignorados.
> - Cobertura de testes (25 testes unitários cobrindo detector, comparador e scraper).
> - Logs estruturados + modo dry-run + filtro por ID via env/CLI.

---

## Como funciona

```
GitHub Actions (diário 08:00 BRT)
  └─► main.py
        ├─► scraper.fetch_project(id)        [HTTP + parsing]
        ├─► comparador.comparar(anterior, novo)
        │     └─► diff? ─── não ──► segue para o próximo
        │             │
        │             sim
        │             ▼
        ├─► save_estado()                    [data/{id}.json]
        ├─► detector.is_approved(state)
        │     └─► aprovado? ── não ──► ignora (sem Telegram)
        │              │
        │              sim
        │              ▼
        └─► notificador.enviar_aprovacao()   [Telegram]
```

## Regra de aprovação

Um projeto é **aprovado** quando a **descrição do último andamento** (o mais recente) contém, ignorando acentos e capitalização:

- `taxa do projeto gerada`, ou
- `emissão de taxa final`

Caso contrário, é **pendente** → nenhuma notificação é enviada (mas o estado é salvo).

Exemplos reais:

| ID | Último andamento | Detectado como |
|----|------------------|----------------|
| 19474 | "Taxa do projeto gerada e solicitação encerrada. Motivo: ..." | ✅ aprovado |
| 46753 | "Taxa do projeto gerada e solicitação encerrada. Motivo: Documentação e projeto deferidos, apto à emissão de taxa final." | ✅ aprovado |
| 45753 | "Projeto redistribuido." | ❌ pendente |
| 47847 | "Análise do projeto encontrou inconsistências. Encaminhada para o contribuinte Motivo: ATENDER AO DESPACHO. PROJETO NÃO APTO." | ❌ pendente |

## Configuração

### 1. Fork / clone o repositório

### 2. Configure os Secrets no GitHub

**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Descrição |
|--------|-----------|
| `TELEGRAM_BOT_TOKEN` | Token do seu bot (obtenha via [@BotFather](https://t.me/BotFather)) |
| `TELEGRAM_CHAT_ID`   | ID do chat/grupo que receberá as notificações |

> Para descobrir o `TELEGRAM_CHAT_ID`: envie qualquer mensagem ao bot e abra
> `https://api.telegram.org/bot<TOKEN>/getUpdates`.

### 3. Configure os projetos monitorados

Edite `projetos.json`:

```json
[
  { "id": 19474, "tipo_alvara": 2, "nome": "Empreendimentos Rio Vermelho" },
  { "id": 47070, "tipo_alvara": 2, "nome": "QD 5, PERIMETRAL NORTE - CONVIDA" }
]
```

> O campo `nome` é opcional — quando ausente, é exibido como `Projeto {id}`.
> O campo `tipo_alvara` segue o padrão da URL (`TipoAlvara=2` = Aprovação de Projeto).

### 4. Primeiro run

Na primeira execução o monitor salva o estado inicial **sem** notificar. A partir da segunda, qualquer mudança no projeto passa pelo detector de aprovação.

Para rodar manualmente: **Actions → Monitor AlvaráFácil → Run workflow**.

## Uso local

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar (precisa das variáveis TELEGRAM_* no ambiente, ou .env)
python main.py

# Rodar sem enviar Telegram (dry-run)
DRY_RUN=1 python main.py

# Filtrar projetos por ID
ONLY_IDS=19474,47847 python main.py

# Forçar refetch + reavaliação
FORCE=1 python main.py

# Rodar testes
python -m pytest tests/ -v

# Validar detecção com os dados já salvos
python validar_ids_reais.py
```

## Estrutura de arquivos

```
alvarafacil-monitor/
├── .github/workflows/monitor.yml   # Cron diário + workflow_dispatch
├── src/
│   ├── __init__.py
│   ├── scraper.py                  # HTTP + parsing (retries, sessão)
│   ├── comparador.py               # diff entre snapshots
│   ├── detector.py                 # regra de aprovação (palavras-chave)
│   └── notificador.py              # envio Telegram
├── tests/
│   ├── conftest.py
│   ├── test_detector.py            # casos aprovado × pendente
│   ├── test_comparador.py
│   └── test_scraper.py
├── data/
│   └── {projeto_id}.json           # snapshot por projeto (auto-gerado)
├── main.py                         # orquestrador
├── projetos.json                   # lista de IDs a monitorar
├── validar_ids_reais.py            # script dev: valida detector com IDs reais
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Como ajustar a regra de aprovação

A lista de palavras-chave fica em [`src/detector.py`](src/detector.py):

```python
APPROVAL_KEYWORDS: tuple[str, ...] = (
    "taxa do projeto gerada",
    "emissao de taxa final",
)
```

Adicione/remova termos aqui e atualize os testes em `tests/test_detector.py`.

## Modelo de notificação (aprovado)

```
✅ *PROJETO APROVADO* — AlvaráFácil
📋 `Empreendimentos Rio Vermelho` (ID: 19474)
🔢 Licença: `30244`
────────────────────────
📅 *Último andamento* (seq 38):
  `11/05/2024 21:48:01`
  > Taxa do projeto gerada e solicitação encerrada. Motivo: ...
  • Situação: `Fechada`
  • Resp.: `VALFRAN DE SOUSA RIBEIRO`

📝 *Outras mudanças:*
  • Andamento #37 (10/05/2024 14:38:00): Solicitação recebida
  • Anexo: `laudo.pdf`

🔗 [Ver no AlvaráFácil](https://www10.goiania.go.gov.br/alvarafacil/...)
```

## Agendamento

Roda todo dia às **08:00 horário de Brasília** (cron `7 11 * * *` UTC).
Para mudar, edite o campo `cron` em `.github/workflows/monitor.yml`.

## Solução de problemas

- **Telegram não recebe nada** — confira `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. Rode com `DRY_RUN=1` para ver a mensagem nos logs.
- **"Página de erro retornada para projeto X"** — o ID não existe ou está bloqueado pelo servidor. Verifique manualmente no site.
- **Timeouts aleatórios** — a SEPLAN às vezes responde devagar. O scraper tem retry automático (3 tentativas, backoff 1.5s).
- **Quero testar com 1 projeto só** — `ONLY_IDS=19474 python main.py` ou `python main.py --only 19474`.
