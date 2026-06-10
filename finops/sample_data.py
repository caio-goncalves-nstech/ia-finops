"""Gerador de dados de demonstração — 6 meses de custos, orçamento e ROL.

Inclui anomalias plantadas (picos e derivas) para demonstrar a detecção.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import db
from .ingest import import_custos, import_orcamento, import_receita

# (provider, empresa, centro_custo, projeto, custo_diario_base)
_SERIES = [
    ("AWS",    "NSTECH",      "CC-1001", "Plataforma Core",   1600.0),
    ("AWS",    "NSTECH",      "CC-1002", "App Mobile",         420.0),
    ("AWS",    "Logistics BR","CC-3001", "Torre de Controle",  950.0),
    ("Azure",  "NSTECH",      "CC-2002", "Data Lake",          780.0),
    ("Azure",  "Logistics BR","CC-3002", "Integrações",        310.0),
    ("GCP",    "NSTECH",      "CC-2002", "Data Science",       260.0),
    ("Datadog","NSTECH",      "CC-1001", "Plataforma Core",    180.0),
    ("AWS",    "NÃO ALOCADO", "NÃO ALOCADO", "NÃO ALOCADO",    120.0),
]


def load_demo(today: date | None = None, months: int = 6, seed: int = 42) -> dict:
    """Limpa a base e carrega o cenário de demonstração."""
    rng = np.random.default_rng(seed)
    today = today or date.today()
    start = (today.replace(day=1) - timedelta(days=30 * (months - 1))).replace(day=1)

    dias = pd.date_range(start, today, freq="D")
    rows = []
    for prov, emp, cc, proj, base in _SERIES:
        growth = rng.uniform(0.000, 0.0025)            # deriva diária leve
        for i, d in enumerate(dias):
            val = base * (1 + growth) ** i
            val *= 0.88 if d.weekday() >= 5 else 1.0   # fim de semana mais barato
            val *= rng.normal(1.0, 0.06)
            rows.append((d.date().isoformat(), prov, emp, cc, proj, "", round(val, 2)))

    custos = pd.DataFrame(rows, columns=[
        "data", "provider", "empresa", "centro_custo", "projeto", "servico", "valor"])

    # --- anomalias plantadas ---------------------------------------------
    def _spike(mask_dia: str, prov: str, cc: str, fator: float):
        m = (custos["data"] == mask_dia) & (custos["provider"] == prov) & \
            (custos["centro_custo"] == cc)
        custos.loc[m, "valor"] *= fator

    d1 = (today - timedelta(days=9)).isoformat()   # pico AWS Plataforma Core
    d2 = (today - timedelta(days=3)).isoformat()   # pico Azure Data Lake
    _spike(d1, "AWS", "CC-1001", 3.8)
    _spike(d2, "Azure", "CC-2002", 4.5)
    # deriva forte no GCP no mês corrente (anomalia MoM)
    mes_atual = today.strftime("%Y-%m")
    m = (custos["provider"] == "GCP") & (custos["data"].str.startswith(mes_atual))
    custos.loc[m, "valor"] *= 1.65

    # --- orçamento ----------------------------------------------------------
    comps = sorted({d.strftime("%Y-%m") for d in dias})
    orc_rows = []
    for prov, emp, cc, proj, base in _SERIES:
        if emp == "NÃO ALOCADO":
            continue
        for comp in comps:
            dias_mes = pd.Period(comp).days_in_month
            mensal = base * dias_mes
            orc_rows.append((comp, prov, emp, cc, proj, round(mensal * rng.normal(1.0, 0.07), 2)))

    orcamento = pd.DataFrame(orc_rows, columns=[
        "competencia", "provider", "empresa", "centro_custo", "projeto", "valor"])

    # --- ROL (Receita Operacional Líquida) por empresa ----------------------
    _ROL_BASE = {"NSTECH": 2_500_000.0, "Logistics BR": 850_000.0}
    rec_rows = []
    for i, comp in enumerate(comps):
        for emp, base_rol in _ROL_BASE.items():
            # receita cresce ~1,5% a.m. com ruído leve
            rec_rows.append((comp, emp, round(base_rol * (1.015 ** i) * rng.normal(1.0, 0.03), 2)))
    receita = pd.DataFrame(rec_rows, columns=["competencia", "empresa", "valor"])

    db.clear_all()
    n_c, _ = import_custos(custos, origem="demo")
    n_o, _ = import_orcamento(orcamento, origem="demo")
    n_r, _ = import_receita(receita, origem="demo")
    return {"custos": n_c, "orcamento": n_o, "receita": n_r}
