"""Camada de persistência — SQLite local.

O banco fica em ``finops.db`` na raiz do projeto. Todas as tabelas usam as
mesmas dimensões de alocação (provider, empresa, centro_custo, projeto),
seguindo a prática FinOps de hierarquia de alocação consistente.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "finops.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS custos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,              -- YYYY-MM-DD (granularidade diária)
    provider TEXT NOT NULL,
    empresa TEXT NOT NULL,
    centro_custo TEXT NOT NULL,
    projeto TEXT NOT NULL,
    servico TEXT DEFAULT '',
    valor REAL NOT NULL,
    moeda TEXT DEFAULT 'BRL',
    origem TEXT DEFAULT 'excel'      -- excel | api | demo
);
CREATE INDEX IF NOT EXISTS ix_custos_data ON custos (data);
CREATE INDEX IF NOT EXISTS ix_custos_dims ON custos (provider, empresa, centro_custo, projeto);

CREATE TABLE IF NOT EXISTS orcamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competencia TEXT NOT NULL,       -- YYYY-MM
    provider TEXT NOT NULL,
    empresa TEXT NOT NULL,
    centro_custo TEXT NOT NULL,
    projeto TEXT NOT NULL,
    valor REAL NOT NULL,
    origem TEXT DEFAULT 'excel'
);
CREATE INDEX IF NOT EXISTS ix_orc_comp ON orcamento (competencia);

DROP TABLE IF EXISTS forecast;       -- modelo antigo (rolling forecast), substituído por receita

CREATE TABLE IF NOT EXISTS receita (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competencia TEXT NOT NULL,       -- YYYY-MM
    empresa TEXT NOT NULL,           -- ROL é apurada por empresa/unidade de negócio
    valor REAL NOT NULL,             -- Receita Operacional Líquida do mês
    origem TEXT DEFAULT 'excel'
);
CREATE INDEX IF NOT EXISTS ix_rec_comp ON receita (competencia);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def insert_df(table: str, df: pd.DataFrame) -> int:
    """Insere um DataFrame já validado na tabela indicada. Retorna nº de linhas."""
    with get_conn() as conn:
        df.to_sql(table, conn, if_exists="append", index=False)
    return len(df)


def replace_period(table: str, df: pd.DataFrame, period_col: str) -> int:
    """Substitui (delete+insert) os períodos presentes no DataFrame.

    Evita duplicidade ao reimportar o mesmo mês/dia — comportamento idempotente,
    recomendado para cargas recorrentes via API ou planilha.
    """
    periods = sorted(df[period_col].unique().tolist())
    with get_conn() as conn:
        qmarks = ",".join("?" * len(periods))
        conn.execute(f"DELETE FROM {table} WHERE {period_col} IN ({qmarks})", periods)
        df.to_sql(table, conn, if_exists="append", index=False)
    return len(df)


def read_table(table: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql(f"SELECT * FROM {table}", conn)
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"])
    return df


def clear_all() -> None:
    with get_conn() as conn:
        for t in ("custos", "orcamento", "receita"):
            conn.execute(f"DELETE FROM {t}")


def row_counts() -> dict:
    with get_conn() as conn:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("custos", "orcamento", "receita")
        }
