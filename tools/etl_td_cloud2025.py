"""ETL: TD Cloud 2025.xlsx → data/demo2/ (base de demonstração 2).

Fontes dentro do workbook:
- "Valores Fornecedor": custos realizados (Act 2025 completo + Act 2026 jan-abr,
  custo POSITIVO) e orçamento 2025 (Bgt - */25, positivo). Grão: BU × Empresa ×
  Alocação P&L × Distribuidor × Fornecedor.
- "Bgt": orçamento 2026 por Empresa × Fornecedor, custo NEGATIVO (sinal invertido
  na carga). Nomes de empresa/fornecedor em vocabulário próprio — normalizados.
- "Valores Empresa": ROL (Receita Operacional Líquida) realizada 2026 jan-abr por
  empresa (cols 18-29). Linhas de Total/Ativação excluídas.

Uso:  python tools/etl_td_cloud2025.py "<caminho do xlsx>"
Saída: data/demo2/custos.csv, orcamento.csv, receita.csv (grão mensal)
       + relatório de conciliação no stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "demo2"

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

# Vocabulários de empresa divergem entre abas (Bgt usa "KMM", VF usa "KMM MG"...)
EMPRESA_CANON = {
    "kmm": "KMM MG", "hive": "HiveCloud", "hivecloud": "HiveCloud",
    "tns match": "TNS Match", "e-frete pedagio": "e-frete Pedágio",
    "e-frete pedágio": "e-frete Pedágio", "routeasy": "Routeasy",
    "logone": "LogOne", "mundo logistica": "Mundo Logística",
    "ats jornada": "ATSlog", "ats - jornada": "ATSlog", "ats logistica": "ATSlog",
    "ats - logistica": "ATSlog", "atslog jornada": "ATSlog", "atslog outros": "ATSlog",
    "atua redes": "Atua Redes", "frete rapido": "Frete Rápido",
    "digitalcomm": "digitalcomm", "qualp": "Qualp",
}

# Fornecedores da aba "Bgt" (razões sociais) → vocabulário da "Valores Fornecedor"
def _canon_provider(nome) -> str:
    if pd.isna(nome) or not str(nome).strip():
        return "ND"
    n = str(nome).strip()
    u = n.upper()
    if "TELTEC" in u:
        return "Azure"
    if "AMAZON" in u or u == "AWS" or "AWS SERVICOS" in u:
        return "Amazon AWS"
    if "GOOGLE" in u or u in ("G CLOUD", "G. CLOUD"):
        return "G Cloud"
    if "ORACLE" in u:
        return "Oracle"
    if "WASABI" in u:
        return "Wasabi Technologies"
    if "MONGODB" in u:
        return "MongoDB"
    if "CLARANET" in u:
        return "Claranet"
    if "SKYONE" in u:
        return "SkyOne"
    if "MICROSOFT" in u:
        return "Microsoft"
    if u in ("ND", "NDI-NSTECH GR", "-"):
        return "ND"
    return n


def _canon_empresa(nome) -> str:
    if pd.isna(nome) or not str(nome).strip():
        return "NÃO ALOCADO"
    n = str(nome).strip().rstrip("*").strip()
    return EMPRESA_CANON.get(n.casefold(), n)


def _melt_meses(df: pd.DataFrame, dims: list[str], col_map: dict[str, str],
                origem_cols: list[str]) -> pd.DataFrame:
    """Unpivot de colunas mensais ('Act - Jan/25' → competencia '2025-01')."""
    out = df[dims + origem_cols].melt(id_vars=dims, var_name="_col", value_name="valor")
    out["competencia"] = out["_col"].map(col_map)
    out["valor"] = pd.to_numeric(out["valor"], errors="coerce")  # células '-' viram NaN
    out = out.dropna(subset=["valor"])
    out = out[out["valor"] != 0]
    return out.drop(columns="_col")


def extrai_valores_fornecedor(path: str):
    df = pd.read_excel(path, sheet_name="Valores Fornecedor", header=0)
    for c in ["BU", "Empresa", "Alocação P&L", "Distribuidor", "Fornecedor"]:
        df[c] = df[c].astype(str).str.strip().replace({"nan": ""})
    df["empresa"] = df["Empresa"].map(_canon_empresa)
    df["provider"] = df["Fornecedor"].replace("", "ND")
    df["centro_custo"] = df["BU"].replace("", "NÃO ALOCADO")
    df["projeto"] = df["Alocação P&L"].replace("", "NÃO ALOCADO")
    df["servico"] = df["Distribuidor"].replace("", "ND")
    dims = ["provider", "empresa", "centro_custo", "projeto", "servico"]

    act_cols, act_map = [], {}
    for ano in (25, 26):
        for i, m in enumerate(MESES, 1):
            c = f"Act - {m}/{ano}"
            act_cols.append(c)
            act_map[c] = f"20{ano}-{i:02d}"
    custos = _melt_meses(df, dims, act_map, act_cols)

    bgt_cols = [f"Bgt - {m}/25" for m in MESES]
    bgt_map = {f"Bgt - {m}/25": f"2025-{i:02d}" for i, m in enumerate(MESES, 1)}
    orc25 = _melt_meses(df, ["provider", "empresa", "centro_custo", "projeto"],
                        bgt_map, bgt_cols)

    # mapeamentos empresa→BU / empresa→alocação (modal) p/ enriquecer o orçamento 2026
    mapa_bu = df.groupby("empresa")["centro_custo"].agg(lambda s: s.mode().iat[0])
    mapa_proj = df.groupby("empresa")["projeto"].agg(lambda s: s.mode().iat[0])
    return custos, orc25, mapa_bu.to_dict(), mapa_proj.to_dict()


def extrai_bgt_2026(path: str, mapa_bu: dict, mapa_proj: dict) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Bgt", header=1)
    df = df.dropna(subset=["Empresa"])
    df["empresa"] = df["Empresa"].map(_canon_empresa)
    df["provider"] = df["Fornecedor"].map(_canon_provider)
    df["centro_custo"] = df["empresa"].map(mapa_bu).fillna("NÃO ALOCADO")
    df["projeto"] = df["empresa"].map(mapa_proj).fillna("NÃO ALOCADO")

    # cabeçalhos dos meses chegam como '1'..'12' (strings)
    col_map = {c: f"2026-{int(float(str(c))):02d}" for c in df.columns
               if str(c).replace(".0", "").isdigit()
               and 1 <= int(float(str(c))) <= 12}
    out = _melt_meses(df, ["provider", "empresa", "centro_custo", "projeto"],
                      col_map, list(col_map))
    out["valor"] = -out["valor"]  # custo é negativo na origem; NDs/recobros mantêm o líquido
    return out


def extrai_receita_2026(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="Valores Empresa", header=None)
    dados = raw.iloc[2:53]  # 51 linhas de empresa; exclui cabeçalhos, totais e ativação
    rows = []
    for _, r in dados.iterrows():
        empresa = _canon_empresa(r[3])
        for mes in range(1, 5):  # ROL realizada fechada: jan-abr/26
            v = pd.to_numeric(r[17 + mes], errors="coerce")  # cols 18-21
            if pd.notna(v) and v != 0:
                rows.append({"competencia": f"2026-{mes:02d}", "empresa": empresa,
                             "valor": float(v)})
    return pd.DataFrame(rows)


def main(path: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    custos, orc25, mapa_bu, mapa_proj = extrai_valores_fornecedor(path)
    orc26 = extrai_bgt_2026(path, mapa_bu, mapa_proj)
    orcamento = pd.concat([orc25, orc26], ignore_index=True)
    receita = extrai_receita_2026(path)

    ordem_c = ["competencia", "provider", "empresa", "centro_custo", "projeto",
               "servico", "valor"]
    ordem_o = ["competencia", "provider", "empresa", "centro_custo", "projeto", "valor"]
    custos[ordem_c].to_csv(OUT_DIR / "custos.csv", index=False, encoding="utf-8")
    orcamento[ordem_o].to_csv(OUT_DIR / "orcamento.csv", index=False, encoding="utf-8")
    receita.to_csv(OUT_DIR / "receita.csv", index=False, encoding="utf-8")

    # ---- conciliação contra os totais lidos diretamente das abas ----------
    def chk(nome, obtido, esperado, tol=0.5):
        ok = abs(obtido - esperado) <= tol
        print(f"{'OK ' if ok else 'ERRO'} {nome}: {obtido:,.2f} (esperado {esperado:,.2f})")
        return ok

    c25 = custos[custos["competencia"].str.startswith("2025")]["valor"].sum()
    c26 = custos[custos["competencia"].str.startswith("2026")]["valor"].sum()
    o25 = orcamento[orcamento["competencia"].str.startswith("2025")]["valor"].sum()
    o26 = orcamento[orcamento["competencia"].str.startswith("2026")]["valor"].sum()
    r26 = receita["valor"].sum()
    tudo_ok = all([
        chk("Custos 2025 (Act VF)", c25, 69_860_821.90),
        chk("Custos 2026 jan-abr (Act VF)", c26, 24_708_603.87),
        chk("Orçamento 2025 (Bgt VF)", o25, 100_227_714.52),
        chk("Orçamento 2026 (aba Bgt)", o26, 84_760_068.26),
        # = soma das linhas de empresa jan-abr, idêntica à linha "Total" da aba
        chk("Receita 2026 jan-abr (VE)", r26, 429_732_110.56),
    ])
    print(f"\nLinhas: custos={len(custos)}, orcamento={len(orcamento)}, receita={len(receita)}")
    if not tudo_ok:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
