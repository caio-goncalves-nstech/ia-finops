# Especificação de Visuais — FinOps Analytics

Documento de referência para reconstruir os gráficos, KPIs e tabelas deste sistema
em qualquer outra plataforma (Power BI, Grafana, web app próprio etc.). Cada visual
está descrito com: objetivo, dados de entrada, regra de cálculo, encoding visual
(tipo, eixos, cores) e racional FinOps.

> Implementação original: Streamlit + Plotly (`app.py`), cálculos em
> `finops/analytics.py` e `finops/anomalies.py`. As regras abaixo independem
> da ferramenta.

---

## 1. Fundamentos compartilhados por todos os visuais

### 1.1 Modelo dimensional
Todo visual cruza no máximo estas dimensões, sempre com os mesmos nomes:

| Dimensão | Presente em | Observação |
|---|---|---|
| `competencia` (AAAA-MM) | custos (derivada da data), orçamento, receita | Grão temporal padrão de comparação |
| `provider` | custos, orçamento | AWS, Azure, GCP, SaaS... |
| `empresa` | custos, orçamento, **receita** | Única dimensão que cruza com ROL |
| `centro_custo` | custos, orçamento | |
| `projeto` | custos, orçamento | |
| `data` (diária) | só custos | Grão usado em anomalias e run-rate |

Custo sem dimensão preenchida vira o membro visível **"NÃO ALOCADO"** — nunca é
descartado nem escondido (princípio FinOps: custo não alocado precisa doer na tela
para ser tratado).

### 1.2 Convenções de formatação
- **Moeda**: `R$ 1.234.567,89` (padrão brasileiro, 2 casas).
- **Percentual de desvio**: sempre com sinal — `+12,3%` / `-4,1%`.
- **Custo/ROL**: 1–2 casas decimais, sufixo `%`.
- **Competência nos eixos**: `AAAA-MM` (ordenável lexicograficamente).

### 1.3 Semântica de cores (consistente em todo o sistema)
| Cor | Hex | Significado |
|---|---|---|
| Azul | `#1f77b4` | Realizado (custo efetivo) — sempre a série "protagonista" |
| Cinza | `#c7c7c7` | Orçado (referência neutra, não é "bom" nem "ruim") |
| Laranja tracejado | `#ff7f0e` | Orçado quando desenhado como linha de referência |
| Verde claro | `#c7e9c0` | ROL/receita (contexto, fica "atrás" do custo) |
| Verde | `#2ca02c` | Desvio favorável (abaixo do orçado) / linha % da ROL |
| Vermelho | `#d62728` | Desvio desfavorável (estouro), anomalias, linha % crítica |

Regra de ouro: **vermelho = gastou mais / piorou; verde = gastou menos / melhorou.**
Em KPIs de custo, setas/deltas usam lógica invertida (subir é ruim → vermelho).

### 1.4 Regras de cálculo transversais
- **Desvio orçamentário**: `desvio = realizado − orçado` (positivo = estouro);
  `desvio% = desvio / orçado × 100`; se orçado = 0, exibir "—" (nunca dividir).
- **Run-rate (projeção de fechamento)**: `MTD ÷ dias_decorridos × dias_do_mês`,
  onde `dias_decorridos` = dia da última data com custo no mês corrente.
- **Custo/ROL**: `realizado ÷ ROL × 100`. **No mês corrente em aberto, usar a
  projeção de run-rate no numerador** — senão o indicador despenca artificialmente
  no início do mês.
- **Mês corrente em comparações MoM**: pro-ratear (`valor ÷ dias_decorridos ×
  dias_do_mês`) antes de comparar com o mês cheio anterior.
- **Junção custo×receita**: somente por `competencia + empresa`; receita não se
  abre por provider/CC/projeto.

### 1.5 Filtros globais
Todos os visuais (exceto telas de administração/importação) respondem ao mesmo
conjunto de filtros: intervalo de competência (slider de faixa) + multiseleção de
provider, empresa, centro de custo e projeto. Filtro vazio = tudo. Tabelas que não
possuem a dimensão filtrada (ex.: receita não tem provider) ignoram esse filtro em
vez de zerar.

---

## 2. Visão Geral (home executiva)

Ordem da página: KPIs → alertas → 2 gráficos lado a lado → visões por dimensão.
A home responde em 5 segundos: "quanto estou gastando, vou estourar, e tem algo
anormal?"

### 2.1 Faixa de 5 KPIs (cards)
| # | KPI | Cálculo | Delta/contexto |
|---|---|---|---|
| 1 | Realizado MTD (mês corrente) | soma dos custos do mês até a última data carregada | — |
| 2 | Projeção de fechamento (run-rate) | regra 1.4 | `% vs orçado` — vermelho se acima |
| 3 | Orçado no mês | soma do orçamento da competência | — |
| 4 | ROL no mês | soma da receita da competência | — |
| 5 | Custo / ROL (projeção do mês) | `projeção ÷ ROL × 100` | `±X p.p. vs média dos 3 meses fechados` — vermelho se subiu |

### 2.2 Alertas condicionais (banners)
- **Cobertura de alocação** (amarelo): aparece se `% alocado < 99,5%`.
  Cálculo: `1 − (custo com qualquer dimensão "NÃO ALOCADO" ÷ custo total)`.
- **Anomalias** (vermelho): aparece se a detecção diária (seção 5) encontrar ≥ 1
  ocorrência no período filtrado, com contagem e link para a página de anomalias.

### 2.3 Gráfico "Evolução mensal — Orçado × Realizado × % da ROL"
- **Tipo**: combo — barras + 2 linhas, eixo Y secundário.
- **X**: competência. **Y esquerdo (R$)**: barras azuis = realizado; linha laranja
  tracejada com marcadores = orçado. **Y direito (%)**: linha verde pontilhada =
  custo/ROL, eixo iniciando em zero, sufixo `%`, sem gridlines (para não poluir).
- **Leitura**: barras acima da linha laranja = meses estourados; a linha verde
  conta se o crescimento do custo acompanha ou não a receita (custo pode subir em
  R$ e cair em % — isso é crescimento saudável).
- **Cuidado**: nunca plotar ROL em R$ no mesmo eixo do custo — a receita é uma
  ordem de magnitude maior e esmaga as barras. Por isso a ROL entra como **%**.

### 2.4 Gráfico "Custo diário por provider"
- **Tipo**: área empilhada (stacked area).
- **X**: data (diária). **Y**: R$ por dia. **Cor**: provider.
- **Leitura**: tendência de curto prazo, sazonalidade semanal (fim de semana mais
  baixo) e picos visíveis a olho nu — é o complemento visual da detecção formal
  de anomalias. Picos detectados aparecem aqui como "morros" destoantes.

### 2.5 Visões por dimensão (abas: Provider / Empresa / Centro de Custo / Projeto)
Cada aba tem o mesmo par de visuais para a dimensão correspondente:
- **Donut** (rosca, furo ~45%): participação do realizado por membro da dimensão.
  Responde "quem gasta mais".
- **Tabela**: membro | realizado | orçado | desvio | desvio% — ordenada por
  realizado desc., com desvio/desvio% coloridos (verde negativo, vermelho positivo)
  e valores em BRL.

---

## 3. Orçado vs Realizado (página analítica)

### 3.1 Controle "Abrir por"
Multiseleção das 4 dimensões — define o agrupamento de toda a página. É o
mecanismo de drill: provider → provider+CC → provider+CC+projeto.

### 3.2 Barras agrupadas por competência
- **Tipo**: barras agrupadas (não empilhadas), 2 séries.
- Cinza neutro = orçado; azul = realizado, lado a lado por mês.
- **Leitura**: comparação mês a mês do total filtrado. Cinza primeiro (referência),
  azul depois (resultado).

### 3.3 Ranking de desvios (tornado/barra horizontal)
- **Tipo**: barras horizontais, uma por combinação de dimensão.
- **X**: desvio em R$ (negativo à esquerda, positivo à direita).
  **Y**: rótulo composto `dim1 | dim2 | ...`, ordenado do maior estouro para a
  maior economia.
- **Cor binária**: vermelho se desvio > 0 (estouro), verde caso contrário.
- **Altura dinâmica**: ~36 px por barra (mínimo 300 px) para nunca espremer rótulos.
- **Leitura**: prioriza a conversa de governança — "onde estourou primeiro".

### 3.4 Tabela analítica + exportação
Colunas: competência | dimensões abertas | realizado | orçado | desvio | desvio%.
Toggle "Somente estouros" (desvio > 0). Exportação CSV com BOM UTF-8 (`utf-8-sig`)
para abrir corretamente no Excel brasileiro.

---

## 4. Realizado vs RoL — Receita Operacional Líquida (unit economics)

Subtítulo fixo do conceito: "quanto da receita o custo de tecnologia consome —
quanto **menor** o %, melhor". Toggle de visão: **Consolidado** | **Por empresa**.

### 4.1 Visão consolidada (combo de contexto + eficiência)
- **Tipo**: barras agrupadas + linha em eixo secundário.
- **Y esquerdo (R$)**: barras verde-claro = ROL (contexto, cor "apagada" de
  propósito); barras azuis = custo realizado.
- **Y direito (%)**: linha vermelha `% da ROL` com **rótulos de dado visíveis**
  (`4,5%`) em cada ponto — o número é o protagonista da página, não pode depender
  de hover.
- **Leitura**: as barras dão escala ("custo é pequeno perto da receita"), a linha
  dá a tendência de eficiência. Meses com `ROL = 0` são excluídos do visual
  (não plotar % infinito).

### 4.2 Visão por empresa
- **Tipo**: linhas com marcadores, uma por empresa.
- **X**: competência. **Y**: custo/ROL em %, eixo começando em zero.
- **Leitura**: benchmark interno entre unidades de negócio — quem opera mais
  eficiente e quem está derivando.

### 4.3 Tabela analítica
competência | (empresa) | custo realizado | ROL | Custo/ROL (%) — moeda em BRL,
% com 2 casas, "—" quando ROL ausente. Exportação CSV idem 3.4.

---

## 5. Anomalias de Consumo

Página com 2 detectores complementares + 1 gráfico de inspeção. Parâmetros
expostos ao usuário em um expander (valores padrão entre parênteses).

### 5.1 Tabela de picos diários (z-score robusto)
- **Algoritmo**: para cada série (combinação de dimensões), agregar custo por dia,
  preencher dias faltantes com 0 (`resample D`), calcular **mediana** e **MAD**
  numa janela móvel de 28 dias **deslocada de 1 dia** (o dia avaliado nunca entra
  na própria baseline); `sigma = 1,4826 × MAD` com piso de `5% da mediana + 1`
  (evita divisão por ~zero em séries estáveis); `z = (valor − mediana) / sigma`.
- **Flag**: `|z| ≥ 3,0` (ajustável 2–5) **e** desvio absoluto ≥ R$ 50/dia (filtro
  de materialidade). Severidade: `alta`; `crítica` se `|z| ≥ 2× limiar`.
- **Mediana/MAD em vez de média/desvio-padrão**: um pico de ontem não contamina a
  baseline de hoje (robustez a outliers é o que evita o "efeito manada" do z-score
  clássico).
- **Multi-visão**: o detector roda em 4 recortes — `provider`, `provider+empresa`,
  `provider+centro_custo`, `empresa+projeto` — e consolida. O mesmo evento pode
  aparecer em mais de um recorte; isso é proposital (ajuda a triangular a origem).
- **Colunas da tabela**: data | dimensão | série | valor | esperado (mediana) |
  desvio | z-score | severidade. Ordenada da data mais recente para trás.
- **Mínimo de histórico**: 7 dias; séries mais novas não geram alerta.

### 5.2 Gráfico de inspeção da série
- **Tipo**: linha temporal (custo diário da série selecionada em um selectbox) com
  **marcadores "X" vermelhos (tamanho 12)** sobre os dias anômalos.
- **Função**: validação visual imediata — o usuário confirma em 2 segundos se o
  alerta é um pico real ou ruído.

### 5.3 Tabela de variações mês a mês (derivas estruturais)
- **Algoritmo**: total mensal por série (mesmos recortes); mês corrente incompleto
  é **pro-rateado** antes de comparar (regra 1.4). Flag se `|variação%| ≥ 30%`
  (ajustável) **e** `|variação R$| ≥ 500` (ajustável). Severidade `crítica` se
  variação ≥ 2× limiar.
- **Racional**: pega o crescimento "lento demais para o z-score diário, rápido
  demais para passar despercebido no fechamento" — ex.: +2%/dia composto.
- **Colunas**: competência | dimensão | série | valor | mês anterior | variação |
  variação% | severidade.

### 5.4 Estados vazios
Quando um detector não encontra nada, exibir confirmação positiva explícita
("Nenhum pico detectado com os parâmetros atuais ✅") — ausência de alerta deve
ser distinguível de "não rodou".

---

## 6. Tela de Importação (visuais de suporte)

- **3 cards de contagem**: linhas carregadas em custos / orçamento / receita —
  feedback imediato de "o que existe na base".
- **Pré-visualização do upload**: 10 primeiras linhas da planilha antes de
  confirmar a importação.
- **Mensagens pós-importação**: sucesso com nº de linhas + avisos de qualidade
  (linhas descartadas por data/valor inválido) como warnings individuais — o
  usuário sabe exatamente o que não entrou e por quê.

---

## 7. Decisões de design que valem para o próximo sistema

1. **Comparação sempre par a par no mesmo visual** (orçado×realizado,
   custo×receita) — nunca obrigar o usuário a cruzar dois gráficos de memória.
2. **% em eixo secundário, nunca R$ de grandezas diferentes no mesmo eixo.**
3. **Projeção de run-rate em destaque na home** — a pergunta executiva é "vou
   estourar?", não "quanto gastei até ontem".
4. **Indicadores do mês em aberto sempre normalizados** (projeção ou pro-rata) —
   comparar mês parcial com mês cheio gera falso alarme ou falsa tranquilidade.
5. **Custo não alocado visível como categoria**, com KPI de cobertura e alerta.
6. **Detecção de anomalias em duas frequências** (pico diário + deriva mensal) e
   em múltiplos recortes dimensionais, com limiares de % E de materialidade em R$
   (um sem o outro gera ruído).
7. **Severidade em 2 níveis** (alta/crítica = 1× e 2× o limiar) — suficiente para
   priorizar sem criar taxonomia que ninguém calibra.
8. **Ranking de desvio horizontal colorido por sinal** — o visual mais eficaz da
   conversa de orçamento; ordene sempre do pior para o melhor.
9. **Toda tabela analítica tem exportação CSV** (UTF-8 com BOM para Excel BR).
10. **Estados vazios informativos** em todas as páginas, com instrução do próximo
    passo ("importe X na página Y").
