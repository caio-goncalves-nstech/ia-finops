# 💰 FinOps Analytics

Aplicação local de FinOps para acompanhar **Orçado vs Realizado**, **Realizado vs RoL
(Receita Operacional Líquida — custo como % da receita)**, **anomalias de consumo** e
visões por **Provider, Empresa, Centro de Custo e Projeto**.

## Como executar

```powershell
pip install -r requirements.txt
streamlit run app.py
```

O navegador abre em `http://localhost:8501`. Na primeira vez, vá em
**📥 Importar Dados → Carregar dados de demonstração** para conhecer os dashboards.

## Como alimentar com dados reais

### Via Excel (hoje)
1. Página **📥 Importar Dados** → baixe os 3 templates (custos, orçamento, receita/ROL).
2. Preencha e faça upload. Cabeçalhos têm tolerância a variações comuns
   (ex.: `Centro de Custo`, `cost_center` e `CC` são aceitos; `receita` e `rol` valem como `valor`).
3. Reimportar o mesmo dia/mês **substitui** os dados daquele período — sem duplicar.

### Via API (futuro)
```powershell
uvicorn api:app --port 8800
```
Documentação interativa em `http://localhost:8800/docs`. Endpoints:
`POST /custos`, `POST /orcamento`, `POST /receita`, `GET /status`.
A validação é a mesma do Excel — os dados caem no mesmo banco (`finops.db`).

## Modelo de dados

| Tabela | Granularidade | Colunas principais |
|---|---|---|
| `custos` | diária | data, provider, empresa, centro_custo, projeto, servico, valor |
| `orcamento` | mensal | competencia, provider, empresa, centro_custo, projeto, valor |
| `receita` (ROL) | mensal | competencia, empresa, valor |

A ROL é apurada por empresa; o nome da empresa na planilha de receita deve bater
com o usado nas planilhas de custo para o cruzamento funcionar.

## Práticas FinOps incorporadas

- **Run-rate / projeção de fechamento**: alerta de estouro antes do fim do mês.
- **Custo / ROL (unit economics)**: % da receita consumido por tecnologia, com
  comparação contra a média histórica — no mês corrente usa a projeção de
  fechamento para não distorcer o indicador.
- **Cobertura de alocação**: custo sem empresa/CC/projeto vira `NÃO ALOCADO` e é
  exposto (não escondido), com KPI de % alocado.
- **Anomalias diárias**: z-score robusto (mediana + MAD) em janela móvel de 28 dias,
  rodado em várias combinações de dimensões.
- **Anomalias MoM**: derivas estruturais que crescem devagar mas estouram o mês
  (mês corrente é pro-rateado para evitar falsos positivos).
- **Ingestão idempotente**: reenviar um período substitui em vez de duplicar.

## Estrutura

```
app.py               # Dashboards (Streamlit)
api.py               # API REST de ingestão (FastAPI)
finops/
  db.py              # SQLite (finops.db)
  ingest.py          # Validação/normalização — comum a Excel e API
  analytics.py       # Orçado vs Realizado, Custo vs ROL, KPIs, run-rate
  anomalies.py       # Detecção de anomalias (z-score + MoM)
  templates.py       # Templates Excel de importação
  sample_data.py     # Dados de demonstração
```
