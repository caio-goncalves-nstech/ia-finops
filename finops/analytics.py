"""Análises FinOps — orçado vs realizado, custo vs RoL (Receita Operacional
Líquida), KPIs e run-rate."""

from __future__ import annotations

import calendar

import pandas as pd

from .ingest import DIM_COLS


def monthly_actual(custos: pd.DataFrame) -> pd.DataFrame:
    """Agrega custos diários em competência mensal por dimensão."""
    if custos.empty:
        return pd.DataFrame(columns=["competencia"] + DIM_COLS + ["realizado"])
    df = custos.copy()
    df["competencia"] = df["data"].dt.strftime("%Y-%m")
    return (
        df.groupby(["competencia"] + DIM_COLS, as_index=False)["valor"]
        .sum()
        .rename(columns={"valor": "realizado"})
    )


def budget_vs_actual(custos: pd.DataFrame, orcamento: pd.DataFrame,
                     group_by: list[str] | None = None) -> pd.DataFrame:
    """Orçado vs Realizado por competência + dimensões escolhidas.

    desvio = realizado - orçado (positivo = estouro).
    """
    dims = group_by if group_by is not None else DIM_COLS
    keys = ["competencia"] + dims

    actual = monthly_actual(custos)
    act = actual.groupby(keys, as_index=False)["realizado"].sum() if not actual.empty \
        else pd.DataFrame(columns=keys + ["realizado"])
    orc = orcamento.groupby(keys, as_index=False)["valor"].sum().rename(
        columns={"valor": "orcado"}) if not orcamento.empty \
        else pd.DataFrame(columns=keys + ["orcado"])

    out = act.merge(orc, on=keys, how="outer")
    out[["realizado", "orcado"]] = out[["realizado", "orcado"]].fillna(0.0)
    out["desvio"] = out["realizado"] - out["orcado"]
    out["desvio_pct"] = out.apply(
        lambda r: (r["desvio"] / r["orcado"] * 100) if r["orcado"] else None, axis=1
    )
    return out.sort_values(keys).reset_index(drop=True)


def cost_vs_rol(custos: pd.DataFrame, receita: pd.DataFrame,
                por_empresa: bool = False) -> pd.DataFrame:
    """Realizado vs RoL: custo como % da Receita Operacional Líquida.

    Unit economics FinOps — quanto da receita o custo de tecnologia consome.
    Quando ``por_empresa=False``, consolida custo total vs ROL total.
    """
    dims = ["empresa"] if por_empresa else []
    keys = ["competencia"] + dims

    actual = monthly_actual(custos)
    act = actual.groupby(keys, as_index=False)["realizado"].sum() if not actual.empty \
        else pd.DataFrame(columns=keys + ["realizado"])
    rec = receita.groupby(keys, as_index=False)["valor"].sum().rename(
        columns={"valor": "rol"}) if not receita.empty \
        else pd.DataFrame(columns=keys + ["rol"])

    out = act.merge(rec, on=keys, how="outer")
    out[["realizado", "rol"]] = out[["realizado", "rol"]].fillna(0.0)
    out["pct_rol"] = out.apply(
        lambda r: (r["realizado"] / r["rol"] * 100) if r["rol"] else None, axis=1
    )
    return out.sort_values(keys).reset_index(drop=True)


def pct_rol_kpi(custos: pd.DataFrame, receita: pd.DataFrame,
                competencia: str, n_meses: int = 3) -> dict:
    """% Custo/ROL do mês e média dos meses fechados anteriores (referência)."""
    serie = cost_vs_rol(custos, receita)
    atual = serie[serie["competencia"] == competencia]["pct_rol"]
    atual = float(atual.iloc[0]) if not atual.empty and pd.notna(atual.iloc[0]) else None
    hist = serie[(serie["competencia"] < competencia) & serie["pct_rol"].notna()]
    hist = hist.sort_values("competencia").tail(n_meses)["pct_rol"]
    media = float(hist.mean()) if not hist.empty else None
    return {"atual": atual, "media_historica": media}


def run_rate(custos: pd.DataFrame, competencia: str) -> dict:
    """Projeção de fechamento do mês pelo ritmo de gasto (run-rate MTD).

    Prática FinOps: comparar a projeção de run-rate com orçamento/forecast dá
    alerta de estouro ANTES do fechamento.
    """
    if custos.empty:
        return {"mtd": 0.0, "projecao": 0.0, "dias_decorridos": 0, "dias_mes": 0}
    df = custos[custos["data"].dt.strftime("%Y-%m") == competencia]
    if df.empty:
        return {"mtd": 0.0, "projecao": 0.0, "dias_decorridos": 0, "dias_mes": 0}
    ano, mes = map(int, competencia.split("-"))
    dias_mes = calendar.monthrange(ano, mes)[1]
    ultimo_dia = df["data"].max().day
    mtd = float(df["valor"].sum())
    projecao = mtd / ultimo_dia * dias_mes
    return {"mtd": mtd, "projecao": projecao, "dias_decorridos": ultimo_dia, "dias_mes": dias_mes}


def allocation_coverage(custos: pd.DataFrame) -> float | None:
    """% do custo corretamente alocado (sem 'NÃO ALOCADO') — KPI de governança."""
    if custos.empty:
        return None
    total = custos["valor"].sum()
    if not total:
        return None
    mask = (custos[DIM_COLS] == "NÃO ALOCADO").any(axis=1)
    return float((1 - custos.loc[mask, "valor"].sum() / total) * 100)
