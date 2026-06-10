"""Ingestão e validação de dados — Excel hoje, API amanhã.

As funções recebem DataFrames, então servem tanto para upload de planilhas
quanto para payloads recebidos pela API (``api.py``). Validação centralizada =
mesma regra de qualidade de dados em qualquer canal de entrada.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

from . import db

DIM_COLS = ["provider", "empresa", "centro_custo", "projeto"]

CUSTOS_COLS = ["data"] + DIM_COLS + ["servico", "valor"]
ORCAMENTO_COLS = ["competencia"] + DIM_COLS + ["valor"]
RECEITA_COLS = ["competencia", "empresa", "valor"]

# Aliases comuns de cabeçalho → nome canônico (tolerância a planilhas "humanas")
_ALIASES = {
    "date": "data", "dia": "data", "data_referencia": "data",
    "mes": "competencia", "periodo": "competencia", "competência": "competencia",
    "provedor": "provider", "cloud": "provider", "fornecedor": "provider",
    "company": "empresa", "unidade": "empresa", "unidade_negocio": "empresa",
    "cc": "centro_custo", "cost_center": "centro_custo", "centro de custo": "centro_custo",
    "centrodecusto": "centro_custo",
    "project": "projeto",
    "service": "servico", "serviço": "servico", "produto": "servico",
    "custo": "valor", "amount": "valor", "cost": "valor", "valor_brl": "valor",
    "receita": "valor", "rol": "valor", "receita_liquida": "valor",
    "receita_operacional_liquida": "valor", "revenue": "valor",
}


def _parse_dates(serie: pd.Series) -> pd.Series:
    """ISO (AAAA-MM-DD) primeiro; só usa dia-primeiro (DD/MM/AAAA) no que sobrar.

    Evita que dateutil com dayfirst inverta mês/dia de datas ISO ambíguas.
    """
    s = serie.astype(str).str.strip()
    parsed = pd.to_datetime(s, errors="coerce", format="ISO8601")
    mask = parsed.isna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
    return parsed


class ValidationError(ValueError):
    """Erro de validação com lista de problemas legível para o usuário."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _norm_header(col: str) -> str:
    col = str(col).strip().lower().replace("-", "_").replace(" ", "_")
    col = "".join(c for c in unicodedata.normalize("NFD", col) if unicodedata.category(c) != "Mn")
    return _ALIASES.get(col, _ALIASES.get(col.replace("_", " "), col))


def _normalize(df: pd.DataFrame, required: list[str], optional: list[str]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_norm_header(c) for c in df.columns]

    problems = []
    missing = [c for c in required if c not in df.columns]
    if missing:
        problems.append(f"Colunas obrigatórias ausentes: {', '.join(missing)}")
        raise ValidationError(problems)

    for c in optional:
        if c not in df.columns:
            df[c] = ""

    df = df[required + optional]
    df = df.dropna(how="all")

    # Dimensões: texto limpo; vazio vira 'NÃO ALOCADO' (visível, não escondido —
    # prática FinOps: custo não alocado precisa aparecer para ser tratado)
    for c in DIM_COLS:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()
            df.loc[df[c] == "", c] = "NÃO ALOCADO"
    for c in ("servico", "versao"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # Valor numérico (aceita '1.234,56' estilo BR)
    if df["valor"].dtype == object:
        df["valor"] = (
            df["valor"].astype(str).str.replace("R$", "", regex=False)
            .str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            .str.strip()
        )
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    bad = df["valor"].isna().sum()
    if bad:
        problems.append(f"{bad} linha(s) com 'valor' não numérico foram descartadas")
        df = df.dropna(subset=["valor"])

    if df.empty:
        problems.append("Nenhuma linha válida após validação")
        raise ValidationError(problems)

    df.attrs["warnings"] = problems
    return df


def normalize_custos(df: pd.DataFrame) -> pd.DataFrame:
    df = _normalize(df, ["data"] + DIM_COLS + ["valor"], ["servico"])
    dates = _parse_dates(df["data"])
    bad = dates.isna().sum()
    if bad:
        df.attrs["warnings"].append(f"{bad} linha(s) com 'data' inválida foram descartadas")
    df = df.loc[dates.notna()].copy()
    df["data"] = dates.dropna().dt.strftime("%Y-%m-%d")
    return df[CUSTOS_COLS]


def _normalize_competencia(serie: pd.Series) -> pd.Series:
    """Aceita '2026-06', '06/2026', datas Excel etc. → 'YYYY-MM'."""
    s = serie.astype(str).str.strip()
    # mm/yyyy → yyyy-mm
    mm_yyyy = s.str.match(r"^\d{1,2}/\d{4}$")
    s.loc[mm_yyyy] = s.loc[mm_yyyy].str.replace(r"^(\d{1,2})/(\d{4})$", r"\2-\1", regex=True)
    parsed = _parse_dates(s)
    out = parsed.dt.strftime("%Y-%m")
    # 'yyyy-mm' puro já é válido
    plain = s.str.match(r"^\d{4}-\d{2}$")
    out.loc[plain] = s.loc[plain]
    return out


def normalize_orcamento(df: pd.DataFrame) -> pd.DataFrame:
    df = _normalize(df, ["competencia"] + DIM_COLS + ["valor"], [])
    comp = _normalize_competencia(df["competencia"])
    bad = comp.isna().sum()
    if bad:
        df.attrs["warnings"].append(f"{bad} linha(s) com 'competencia' inválida foram descartadas")
    df = df.loc[comp.notna()].copy()
    df["competencia"] = comp.dropna()
    return df[ORCAMENTO_COLS]


def normalize_receita(df: pd.DataFrame) -> pd.DataFrame:
    """ROL (Receita Operacional Líquida) mensal por empresa."""
    df = _normalize(df, ["competencia", "empresa", "valor"], [])
    comp = _normalize_competencia(df["competencia"])
    bad = comp.isna().sum()
    if bad:
        df.attrs["warnings"].append(f"{bad} linha(s) com 'competencia' inválida foram descartadas")
    df = df.loc[comp.notna()].copy()
    df["competencia"] = comp.dropna()
    return df[RECEITA_COLS]


def import_custos(df: pd.DataFrame, origem: str = "excel", replace: bool = True) -> tuple[int, list[str]]:
    norm = normalize_custos(df)
    norm["origem"] = origem
    n = db.replace_period("custos", norm, "data") if replace else db.insert_df("custos", norm)
    return n, norm.attrs.get("warnings", [])


def import_orcamento(df: pd.DataFrame, origem: str = "excel", replace: bool = True) -> tuple[int, list[str]]:
    norm = normalize_orcamento(df)
    norm["origem"] = origem
    n = db.replace_period("orcamento", norm, "competencia") if replace else db.insert_df("orcamento", norm)
    return n, norm.attrs.get("warnings", [])


def import_receita(df: pd.DataFrame, origem: str = "excel", replace: bool = True) -> tuple[int, list[str]]:
    norm = normalize_receita(df)
    norm["origem"] = origem
    n = db.replace_period("receita", norm, "competencia") if replace else db.insert_df("receita", norm)
    return n, norm.attrs.get("warnings", [])
