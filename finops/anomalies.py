"""Detecção de anomalias de consumo.

Duas técnicas complementares, ambas práticas recorrentes em FinOps:

1. **Z-score robusto em séries diárias** — para cada combinação de dimensões,
   compara o gasto do dia com a mediana/MAD de uma janela móvel. Pega picos
   súbitos (recurso esquecido ligado, ataque, deploy errado).
2. **Variação mês a mês (MoM)** — pega derivas estruturais que crescem devagar
   demais para disparar o z-score diário, mas estouram o mês.
"""

from __future__ import annotations

import pandas as pd

from .ingest import DIM_COLS


def daily_anomalies(custos: pd.DataFrame,
                    dims: list[str] | None = None,
                    window: int = 28,
                    min_history: int = 7,
                    z_threshold: float = 3.0,
                    min_impact: float = 50.0) -> pd.DataFrame:
    """Anomalias diárias por z-score robusto (mediana + MAD) em janela móvel.

    min_impact filtra ruído: só reporta desvio absoluto >= R$ min_impact/dia.
    """
    cols = ["data", "dimensao", "serie", "valor", "esperado", "desvio", "zscore", "severidade"]
    if custos.empty:
        return pd.DataFrame(columns=cols)
    dims = dims or ["provider", "centro_custo"]

    df = custos.copy()
    df["serie"] = df[dims].agg(" | ".join, axis=1)
    daily = df.groupby(["serie", "data"], as_index=False)["valor"].sum()

    out = []
    for serie, g in daily.groupby("serie"):
        g = g.set_index("data").resample("D")["valor"].sum().reset_index()
        if len(g) < min_history + 1:
            continue
        med = g["valor"].rolling(window, min_periods=min_history).median().shift(1)
        mad = (g["valor"] - med).abs().rolling(window, min_periods=min_history).median().shift(1)
        # 1.4826 * MAD ~ desvio padrão; piso evita divisão por ~zero em séries estáveis
        sigma = (1.4826 * mad).clip(lower=med.abs() * 0.05 + 1.0)
        z = (g["valor"] - med) / sigma
        flag = (z.abs() >= z_threshold) & ((g["valor"] - med).abs() >= min_impact)
        for _, row in g[flag.fillna(False)].iterrows():
            i = row.name
            out.append({
                "data": row["data"],
                "dimensao": " + ".join(dims),
                "serie": serie,
                "valor": row["valor"],
                "esperado": med.iloc[i],
                "desvio": row["valor"] - med.iloc[i],
                "zscore": z.iloc[i],
                "severidade": "crítica" if abs(z.iloc[i]) >= 2 * z_threshold else "alta",
            })
    res = pd.DataFrame(out, columns=cols)
    return res.sort_values(["data", "zscore"], ascending=[False, False]).reset_index(drop=True)


def mom_anomalies(custos: pd.DataFrame,
                  dims: list[str] | None = None,
                  pct_threshold: float = 30.0,
                  min_impact: float = 500.0) -> pd.DataFrame:
    """Variações mês a mês acima do limiar (%) e com impacto mínimo em R$."""
    cols = ["competencia", "dimensao", "serie", "valor", "mes_anterior",
            "variacao", "variacao_pct", "severidade"]
    if custos.empty:
        return pd.DataFrame(columns=cols)
    dims = dims or ["provider", "centro_custo"]

    df = custos.copy()
    df["competencia"] = df["data"].dt.strftime("%Y-%m")
    df["serie"] = df[dims].agg(" | ".join, axis=1)
    mensal = df.groupby(["serie", "competencia"], as_index=False)["valor"].sum()

    # Mês corrente incompleto: pro-rateia pelo ritmo (senão todo mês novo
    # apareceria como queda falsa de ~-50% vs o mês cheio anterior)
    ultima_data = df["data"].max()
    comp_aberta = ultima_data.strftime("%Y-%m")
    dias_mes = ultima_data.days_in_month
    if ultima_data.day < dias_mes:
        m = mensal["competencia"] == comp_aberta
        mensal.loc[m, "valor"] = mensal.loc[m, "valor"] / ultima_data.day * dias_mes

    out = []
    for serie, g in mensal.groupby("serie"):
        g = g.sort_values("competencia").reset_index(drop=True)
        g["anterior"] = g["valor"].shift(1)
        g = g.dropna(subset=["anterior"])
        g = g[g["anterior"] > 0]
        g["var"] = g["valor"] - g["anterior"]
        g["var_pct"] = g["var"] / g["anterior"] * 100
        hits = g[(g["var_pct"].abs() >= pct_threshold) & (g["var"].abs() >= min_impact)]
        for _, row in hits.iterrows():
            out.append({
                "competencia": row["competencia"],
                "dimensao": " + ".join(dims),
                "serie": serie,
                "valor": row["valor"],
                "mes_anterior": row["anterior"],
                "variacao": row["var"],
                "variacao_pct": row["var_pct"],
                "severidade": "crítica" if abs(row["var_pct"]) >= 2 * pct_threshold else "alta",
            })
    res = pd.DataFrame(out, columns=cols)
    return res.sort_values(["competencia", "variacao_pct"],
                           ascending=[False, False]).reset_index(drop=True)


def all_dimension_daily(custos: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Roda a detecção diária em várias visões de dimensão e consolida."""
    views = [["provider"], ["provider", "empresa"],
             ["provider", "centro_custo"], ["empresa", "projeto"]]
    frames = [daily_anomalies(custos, dims=v, **kwargs) for v in views]
    res = pd.concat(frames, ignore_index=True)
    if res.empty:
        return res
    return res.sort_values(["data", "zscore"], ascending=[False, False]).reset_index(drop=True)
