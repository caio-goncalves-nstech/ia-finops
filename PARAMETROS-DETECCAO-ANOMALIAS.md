# Parâmetros de Detecção — Anomalias de Consumo

Contexto aprofundado das regras por trás do expander **"⚙️ Parâmetros de detecção"**
da página **🚨 Anomalias**. Serve como guia de calibração para o usuário e como
especificação para reimplementar a lógica em outro sistema.

> Implementação: `finops/anomalies.py` (funções `daily_anomalies`, `mom_anomalies`
> e `all_dimension_daily`). A página expõe 3 parâmetros; os demais são internos
> com valores fixos, documentados na seção 4.

---

## 1. Visão geral: por que dois detectores

| | Detector diário (picos) | Detector mensal (derivas) |
|---|---|---|
| **Pergunta que responde** | "Algo explodiu **hoje**?" | "Algo vem **crescendo** e vai estourar o mês?" |
| **Técnica** | z-score robusto (mediana + MAD) em janela móvel | variação % mês contra mês anterior |
| **Pega** | recurso esquecido ligado, deploy errado, loop de retry, ataque, repique de autoscaling | crescimento composto lento (~1–3%/dia), mudança de patamar, contrato novo sem orçamento |
| **Cego para** | crescimento gradual (cada dia é "quase normal") | picos de 1–2 dias diluídos no total do mês |
| **Parâmetro exposto** | Sensibilidade (z-score) | Variação MoM mínima (%) + Impacto mínimo (R$) |

Os dois são complementares de propósito: um evento relevante escapa de um e cai no
outro. **Nunca desligue um deles achando que o outro cobre.**

---

## 2. Parâmetro 1 — "Sensibilidade diária (z-score)"

**Slider: 2,0 a 5,0 · passo 0,5 · padrão 3,0**

### O que é
O número de "desvios robustos" que o gasto de um dia precisa se afastar do
comportamento típico da série para virar alerta. É o limiar do teste estatístico:

```
z = (valor_do_dia − mediana_28d) / sigma_robusto
alerta se |z| ≥ limiar  E  |valor_do_dia − mediana_28d| ≥ R$ 50
```

onde:
- `mediana_28d` = mediana do gasto diário nos 28 dias **anteriores** ao dia
  avaliado (o próprio dia nunca entra na baseline — senão um pico "se esconde"
  dentro da própria média);
- `sigma_robusto = 1,4826 × MAD` (MAD = mediana dos desvios absolutos em relação
  à mediana). O fator 1,4826 converte MAD em equivalente do desvio-padrão;
- piso do sigma = `5% da mediana + R$ 1` — em séries muito estáveis o MAD tende a
  zero e qualquer variação de centavos viraria alerta; o piso impede isso.

### Por que mediana/MAD e não média/desvio-padrão
Com média e desvio-padrão clássicos, **o pico de ontem infla a baseline de hoje**:
depois de uma anomalia grande, o detector fica "anestesiado" por semanas (o desvio-
padrão cresce e nada mais parece anômalo). Mediana e MAD praticamente ignoram
outliers passados — a baseline continua representando o comportamento normal.

### Leitura prática do slider
| Valor | Comportamento | Quando usar |
|---|---|---|
| **2,0–2,5** | Muito sensível — variações de ~2× o ruído normal já alertam | Investigação ativa de um incidente; semana de migração/go-live que você quer vigiar de perto |
| **3,0 (padrão)** | Equilíbrio de mercado — em distribuição normal, ~0,3% de falsos positivos por série/dia | Operação do dia a dia |
| **4,0–5,0** | Só eventos gritantes (4–5× o ruído) | Base com muitas séries voláteis gerando ruído; triagem executiva semanal |

### Exemplo numérico
Série `AWS | CC-1001` com mediana de R$ 1.600/dia e MAD de R$ 95:
- `sigma = 1,4826 × 95 ≈ R$ 141`
- Com limiar 3,0 → alerta a partir de `1.600 + 3×141 ≈ R$ 2.023/dia`
- Com limiar 2,0 → alerta a partir de ≈ R$ 1.882/dia
- Com limiar 5,0 → alerta só a partir de ≈ R$ 2.305/dia

### Severidade derivada
- `|z| ≥ limiar` → **alta**
- `|z| ≥ 2 × limiar` → **crítica** (ex.: padrão 3,0 → crítica a partir de z 6,0)

---

## 3. Parâmetros 2 e 3 — "Variação MoM mínima (%)" e "Impacto mínimo MoM (R$)"

**Slider: 10% a 100% · passo 5 · padrão 30%** · **Campo: R$ 0 a 100.000 · padrão R$ 500**

### O que são
Filtro duplo do detector mensal. Um mês só vira alerta se passar **nos dois
critérios ao mesmo tempo**:

```
variação%  = (mês_atual − mês_anterior) / mês_anterior × 100
alerta se |variação%| ≥ limiar_pct  E  |mês_atual − mês_anterior| ≥ impacto_min_R$
```

### Por que os dois juntos (regra de materialidade)
Cada um sozinho gera ruído de um tipo diferente:
- **Só %**: uma série de R$ 40/mês que vai a R$ 80 dispara "+100%" — irrelevante
  financeiramente. Séries pequenas variam muito em percentual.
- **Só R$**: numa série de R$ 500 mil/mês, R$ 600 de variação é flutuação normal —
  mas passaria num filtro puramente absoluto baixo.

A combinação garante que o alerta seja **proporcionalmente anormal E
financeiramente relevante**. Esse é o princípio de materialidade — vale a pena
replicar em qualquer sistema de alertas de custo.

### Calibração sugerida
| Cenário | Variação % | Impacto R$ |
|---|---|---|
| Base pequena / início de operação | 30% | R$ 500 (padrão) |
| Base com gasto mensal de 6 dígitos | 20–30% | R$ 2.000–5.000 |
| Triagem executiva (só o que dói) | 50% | R$ 10.000+ |
| Caça fina pós-incidente | 10–15% | R$ 0–500 |

Regra de bolso para o impacto mínimo: **~0,5% a 1% do gasto mensal total** da
visão analisada.

### Severidade derivada
- `|variação%| ≥ limiar` → **alta**
- `|variação%| ≥ 2 × limiar` → **crítica** (ex.: padrão 30% → crítica a partir de 60%)

### Regra do mês corrente (pro-rata) — automática, não configurável
O mês em aberto é **projetado antes de comparar**:

```
valor_comparável = total_MTD ÷ dias_decorridos × dias_do_mês
```

Sem isso, todo dia 10 o mês corrente apareceria como "queda de -67%" contra o mês
cheio anterior (falso positivo sistemático), e um crescimento real ficaria
invisível até o fechamento. Com o pro-rata, uma deriva de +58% é detectada **no
dia 10, não no dia 30** — esse é o valor do detector. Atenção: nos primeiros ~5
dias do mês a projeção é instável (poucos dias de amostra); trate alertas MoM do
início do mês como indicativos, não conclusivos.

---

## 4. Parâmetros internos (fixos no código, não expostos na tela)

| Parâmetro | Valor | Função | Quando mexer |
|---|---|---|---|
| `window` | 28 dias | Tamanho da janela da baseline diária. 28 = 4 semanas completas, neutraliza sazonalidade semanal (fim de semana mais barato) | Aumentar (56) se houver sazonalidade quinzenal de billing; nunca usar valor que não seja múltiplo de 7 |
| `min_history` | 7 dias | Mínimo de histórico para a série gerar alerta. Série mais nova fica em "período de aprendizado" silencioso | Reduzir torna séries novas barulhentas; aumentar atrasa a proteção de projetos novos |
| `min_impact` (diário) | R$ 50/dia | Materialidade do detector diário — desvio menor que isso nunca alerta, por maior que seja o z | Mesma regra de bolso da seção 3: ~0,5–1% do gasto diário total |
| Piso do sigma | `5% da mediana + R$ 1` | Evita divisão por ~zero em séries estáveis (MAD → 0) | Raramente; subir o piso dessensibiliza séries muito regulares |
| Recortes dimensionais | `provider`, `provider+empresa`, `provider+centro_custo`, `empresa+projeto` | O detector diário roda nas 4 visões e consolida (`all_dimension_daily`) | Adicionar `provider+servico` quando a coluna serviço estiver bem populada |
| Detecção de grão mensal | ≥ 80% das séries×mês com valor diário constante | Bases de grão mensal (valor do mês rateado pelos dias, ex.: razão contábil) desativam automaticamente o detector diário — cada virada de mês viraria falso pico. Só a detecção MoM roda | Se uma base mista (parte diária, parte mensal) suprimir picos indevidamente, baixar o limiar de 0,8 em `monthly_grain_share` |

### Sobre o mesmo evento aparecer em vários recortes
Um pico em `AWS | CC-1001` aparece também em `AWS` (provider) e `AWS | NSTECH`
(provider+empresa). **Não é duplicação acidental** — é triangulação: se o alerta
aparece no provider mas não em nenhum centro de custo específico, o problema está
pulverizado; se aparece concentrado num CC, o dono é claro. Num sistema futuro,
pode-se agrupar os alertas por (data, valor) e exibir os recortes como detalhe.

---

## 5. Como calibrar na prática (roteiro)

1. **Comece nos padrões** (z=3,0 · MoM=30% · R$ 500) e rode por 2 semanas.
2. **Conte os alertas acionáveis**: a meta é que **>50% dos alertas gerem uma
   ação** (desligar recurso, abrir chamado, justificar com o dono do CC).
3. Muitos alertas ignorados → **suba** o impacto mínimo primeiro (corta ruído
   pequeno sem perder eventos grandes); só depois suba o z/%.
4. Incidente real passou batido → identifique em qual detector deveria ter caído:
   - pico de 1 dia não pego → **desça o z** para 2,5;
   - crescimento lento não pego → **desça o MoM%** para 20%.
5. **Reavalie a cada mudança estrutural da base** (novo provider, migração,
   reorganização de CCs): séries novas passam pelo período de aprendizado e o
   perfil de ruído muda.

**Anti-padrão a evitar**: zerar o impacto mínimo "para não perder nada". O custo
de 30 alertas/dia irrelevantes é o time parar de olhar — e aí o alerta importante
passa batido junto. Falso negativo barato < fadiga de alerta cara.

---

## 6. Resumo de uma linha por parâmetro

| Parâmetro | Em uma frase |
|---|---|
| Sensibilidade z-score | "Quantas vezes o ruído normal um dia precisa estourar para me avisar" |
| Variação MoM mínima | "Quanto % o mês precisa crescer/cair sobre o anterior para me avisar" |
| Impacto mínimo R$ | "Abaixo deste valor em R$, não me incomode — não é material" |
| Janela 28d (interno) | "O que é 'normal' = as últimas 4 semanas, sem o dia avaliado" |
| Histórico mínimo 7d (interno) | "Série nova fica uma semana em silêncio aprendendo o padrão" |
| Pro-rata do mês corrente (interno) | "Mês em aberto é comparado pelo ritmo projetado, não pelo parcial" |
