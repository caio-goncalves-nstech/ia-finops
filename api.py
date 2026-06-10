"""API REST de ingestão FinOps — mesmo pipeline de validação do Excel.

Execução:  uvicorn api:app --port 8800
Docs interativas:  http://localhost:8800/docs

Exemplo:
    POST /custos
    [{"data": "2026-06-01", "provider": "AWS", "empresa": "NSTECH",
      "centro_custo": "CC-1001", "projeto": "Plataforma Core",
      "servico": "EC2", "valor": 1523.45}]
"""

from __future__ import annotations

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from finops import db
from finops.ingest import (ValidationError, import_custos, import_orcamento,
                           import_receita)

app = FastAPI(
    title="FinOps Ingestion API",
    description="Ingestão de custos, orçamento e receita operacional líquida (ROL). "
                "Reenvio do mesmo período substitui os dados (idempotente).",
    version="1.0.0",
)


class CustoIn(BaseModel):
    data: str = Field(examples=["2026-06-01"])
    provider: str
    empresa: str
    centro_custo: str
    projeto: str
    servico: str = ""
    valor: float


class OrcamentoIn(BaseModel):
    competencia: str = Field(examples=["2026-06"])
    provider: str
    empresa: str
    centro_custo: str
    projeto: str
    valor: float


class ReceitaIn(BaseModel):
    competencia: str = Field(examples=["2026-06"])
    empresa: str
    valor: float = Field(description="Receita Operacional Líquida do mês em R$")


def _ingest(items: list[BaseModel], fn) -> dict:
    if not items:
        raise HTTPException(422, "Payload vazio")
    df = pd.DataFrame([i.model_dump() for i in items])
    try:
        n, warns = fn(df, origem="api")
    except ValidationError as e:
        raise HTTPException(422, detail=e.problems)
    return {"linhas_importadas": n, "avisos": warns}


@app.post("/custos", summary="Importa custos diários (realizado)")
def post_custos(items: list[CustoIn]):
    return _ingest(items, import_custos)


@app.post("/orcamento", summary="Importa orçamento mensal")
def post_orcamento(items: list[OrcamentoIn]):
    return _ingest(items, import_orcamento)


@app.post("/receita", summary="Importa ROL (Receita Operacional Líquida) mensal por empresa")
def post_receita(items: list[ReceitaIn]):
    return _ingest(items, import_receita)


@app.get("/status", summary="Linhas carregadas por tabela")
def status():
    return db.row_counts()
