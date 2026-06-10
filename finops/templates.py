"""Geração dos templates Excel de importação (custos, orçamento, receita/ROL)."""

from __future__ import annotations

import io

import pandas as pd

_EXEMPLO_CUSTOS = pd.DataFrame([
    {"data": "2026-06-01", "provider": "AWS", "empresa": "NSTECH", "centro_custo": "CC-1001",
     "projeto": "Plataforma Core", "servico": "EC2", "valor": 1523.45},
    {"data": "2026-06-01", "provider": "Azure", "empresa": "NSTECH", "centro_custo": "CC-2002",
     "projeto": "Data Lake", "servico": "Synapse", "valor": 880.10},
])

_EXEMPLO_ORCAMENTO = pd.DataFrame([
    {"competencia": "2026-06", "provider": "AWS", "empresa": "NSTECH",
     "centro_custo": "CC-1001", "projeto": "Plataforma Core", "valor": 50000.00},
])

_EXEMPLO_RECEITA = pd.DataFrame([
    {"competencia": "2026-06", "empresa": "NSTECH", "valor": 2500000.00},
    {"competencia": "2026-06", "empresa": "Logistics BR", "valor": 900000.00},
])

_INSTRUCOES = {
    "custos": [
        ["Template de CUSTOS (realizado) — granularidade diária"],
        [""],
        ["Coluna", "Obrigatória", "Formato / Exemplo"],
        ["data", "Sim", "AAAA-MM-DD ou DD/MM/AAAA"],
        ["provider", "Sim", "AWS, Azure, GCP, Oracle, Datadog..."],
        ["empresa", "Sim", "Empresa / unidade de negócio"],
        ["centro_custo", "Sim", "Ex.: CC-1001"],
        ["projeto", "Sim", "Nome do projeto"],
        ["servico", "Não", "Ex.: EC2, S3, AKS"],
        ["valor", "Sim", "Número. Aceita 1234.56 ou 1.234,56"],
        [""],
        ["Reimportar o mesmo dia substitui os dados daquele dia (sem duplicar)."],
    ],
    "orcamento": [
        ["Template de ORÇAMENTO — granularidade mensal"],
        [""],
        ["Coluna", "Obrigatória", "Formato / Exemplo"],
        ["competencia", "Sim", "AAAA-MM ou MM/AAAA"],
        ["provider", "Sim", "AWS, Azure, GCP..."],
        ["empresa", "Sim", "Empresa / unidade de negócio"],
        ["centro_custo", "Sim", "Ex.: CC-1001"],
        ["projeto", "Sim", "Nome do projeto"],
        ["valor", "Sim", "Valor orçado do mês"],
    ],
    "receita": [
        ["Template de RECEITA OPERACIONAL LÍQUIDA (ROL) — granularidade mensal"],
        [""],
        ["Coluna", "Obrigatória", "Formato / Exemplo"],
        ["competencia", "Sim", "AAAA-MM ou MM/AAAA"],
        ["empresa", "Sim", "Empresa / unidade de negócio (igual à usada nos custos)"],
        ["valor", "Sim", "ROL do mês em R$"],
        [""],
        ["Usada para calcular o custo de tecnologia como % da receita."],
        ["O nome da empresa deve bater com o usado nas planilhas de custo."],
    ],
}

_EXEMPLOS = {"custos": _EXEMPLO_CUSTOS, "orcamento": _EXEMPLO_ORCAMENTO,
             "receita": _EXEMPLO_RECEITA}


def build_template(kind: str) -> bytes:
    """Gera o template .xlsx em memória (aba de dados + aba de instruções)."""
    exemplo = _EXEMPLOS[kind]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        exemplo.to_excel(writer, sheet_name="dados", index=False)
        pd.DataFrame(_INSTRUCOES[kind]).to_excel(
            writer, sheet_name="instrucoes", index=False, header=False)
    return buf.getvalue()
