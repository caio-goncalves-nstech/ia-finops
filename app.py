"""FinOps Analytics — orçado vs realizado, custo vs RoL (Receita Operacional
Líquida), anomalias e visões por dimensão.

Execução:  streamlit run app.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from finops import analytics, anomalies, db
from finops.ingest import (DIM_COLS, ValidationError, import_custos,
                           import_orcamento, import_receita)
from finops.sample_data import demo2_available, load_demo, load_demo2
from finops.templates import build_template

st.set_page_config(page_title="FinOps Analytics", page_icon="💰", layout="wide")

DIM_LABELS = {"provider": "Provider", "empresa": "Empresa",
              "centro_custo": "Centro de Custo", "projeto": "Projeto"}


# ---------------------------------------------------------------- utilidades
def brl(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%"


@st.cache_data(ttl=60)
def load_data():
    return db.read_table("custos"), db.read_table("orcamento"), db.read_table("receita")


def style_desvio(df: pd.DataFrame, money_cols: list[str], pct_cols: list[str]):
    def _color(v):
        if pd.isna(v):
            return ""
        return "color: #d62728" if v > 0 else "color: #2ca02c"
    sty = df.style
    for c in money_cols:
        sty = sty.format(brl, subset=[c])
    for c in pct_cols:
        sty = sty.format(pct, subset=[c]).map(_color, subset=[c])
    if "desvio" in df.columns:
        sty = sty.map(_color, subset=["desvio"])
    return sty


def apply_filters(custos, orcamento, receita):
    """Filtros globais na sidebar; valem para todas as páginas."""
    st.sidebar.divider()
    st.sidebar.subheader("Filtros")

    comps = sorted(set(
        ([] if custos.empty else custos["data"].dt.strftime("%Y-%m").unique().tolist())
        + ([] if orcamento.empty else orcamento["competencia"].unique().tolist())
        + ([] if receita.empty else receita["competencia"].unique().tolist())
    ))
    sel = {}
    if comps:
        ini, fim = st.sidebar.select_slider(
            "Período (competência)", options=comps, value=(comps[0], comps[-1]))
        sel["comp"] = (ini, fim)

    for dim in DIM_COLS:
        opts = sorted(set(
            ([] if custos.empty else custos[dim].unique().tolist())
            + ([] if orcamento.empty else orcamento[dim].unique().tolist())
            + ([] if receita.empty or dim not in receita.columns
               else receita[dim].unique().tolist())
        ))
        if opts:
            chosen = st.sidebar.multiselect(DIM_LABELS[dim], opts, default=[])
            if chosen:
                sel[dim] = chosen

    def _f(df, comp_col=None):
        if df.empty:
            return df
        out = df
        if "comp" in sel and comp_col:
            c = out[comp_col].dt.strftime("%Y-%m") if comp_col == "data" else out[comp_col]
            out = out[(c >= sel["comp"][0]) & (c <= sel["comp"][1])]
        for dim in DIM_COLS:
            if dim in sel and dim in out.columns:
                out = out[out[dim].isin(sel[dim])]
        return out

    return _f(custos, "data"), _f(orcamento, "competencia"), _f(receita, "competencia")


# ------------------------------------------------------------------- páginas
def page_overview(custos, orcamento, receita):
    st.title("💰 FinOps — Visão Geral")
    if custos.empty:
        st.info("Nenhum custo carregado. Vá em **Importar Dados** para subir planilhas "
                "ou carregar os dados de demonstração.")
        return

    comp_atual = custos["data"].max().strftime("%Y-%m")
    bva = analytics.budget_vs_actual(custos, orcamento, group_by=[])
    cvr = analytics.cost_vs_rol(custos, receita)
    rr = analytics.run_rate(custos, comp_atual)

    linha_orc = bva[bva["competencia"] == comp_atual]
    linha_rol = cvr[cvr["competencia"] == comp_atual]
    orcado = float(linha_orc["orcado"].sum())
    rol = float(linha_rol["rol"].sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"Realizado MTD ({comp_atual})", brl(rr["mtd"]))
    c2.metric("Projeção de fechamento (run-rate)", brl(rr["projecao"]),
              delta=pct((rr["projecao"] / orcado - 1) * 100 if orcado else None) + " vs orçado"
              if orcado else None, delta_color="inverse")
    c3.metric("Orçado no mês", brl(orcado))
    c4.metric("ROL no mês", brl(rol))
    kpi = analytics.pct_rol_kpi(custos, receita, comp_atual)
    # no mês corrente, % sobre a projeção de fechamento evita % artificialmente baixo
    pct_proj = (rr["projecao"] / rol * 100) if rol else None
    c5.metric("Custo / ROL (projeção do mês)",
              f"{pct_proj:.1f}%" if pct_proj is not None else "—",
              delta=(f"{pct_proj - kpi['media_historica']:+.1f} p.p. vs média 3m"
                     if pct_proj is not None and kpi["media_historica"] is not None else None),
              delta_color="inverse",
              help="Custo de tecnologia como % da Receita Operacional Líquida "
                   "(projeção de fechamento ÷ ROL do mês).")

    cov = analytics.allocation_coverage(custos)
    if cov is not None and cov < 99.5:
        st.warning(f"🏷️ Cobertura de alocação: **{cov:.1f}%** do custo está corretamente "
                   "alocado. O restante aparece como 'NÃO ALOCADO' — trate a alocação "
                   "para melhorar a confiabilidade do showback.")

    if anomalies.monthly_grain_share(custos) < 0.8:
        n_anom = len(anomalies.daily_anomalies(custos))
        if n_anom:
            st.error(f"🚨 **{n_anom} anomalia(s) de consumo diário** detectada(s) no "
                     "período. Veja a página **Anomalias**.")
    else:
        n_mom = len(anomalies.mom_anomalies(custos))
        if n_mom:
            st.error(f"🚨 **{n_mom} variação(ões) mensal(is) atípica(s)** detectada(s) "
                     "no período. Veja a página **Anomalias**.")

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Evolução mensal — Orçado × Realizado × % da ROL")
        serie = bva.merge(cvr[["competencia", "pct_rol"]], on="competencia", how="outer")
        serie[["realizado", "orcado"]] = serie[["realizado", "orcado"]].fillna(0)
        fig = go.Figure()
        fig.add_bar(x=serie["competencia"], y=serie["realizado"], name="Realizado",
                    marker_color="#1f77b4")
        fig.add_scatter(x=serie["competencia"], y=serie["orcado"], name="Orçado",
                        mode="lines+markers", line=dict(color="#ff7f0e", dash="dash"))
        fig.add_scatter(x=serie["competencia"], y=serie["pct_rol"], name="% da ROL",
                        mode="lines+markers", yaxis="y2",
                        line=dict(color="#2ca02c", dash="dot"))
        fig.update_layout(
            height=380, margin=dict(t=10, b=10), legend=dict(orientation="h"),
            yaxis2=dict(overlaying="y", side="right", ticksuffix="%",
                        rangemode="tozero", showgrid=False))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Custo diário por provider")
        daily = custos.copy()
        daily = daily.groupby([daily["data"].dt.date, "provider"], as_index=False)["valor"].sum()
        daily.columns = ["data", "provider", "valor"]
        fig = px.area(daily, x="data", y="valor", color="provider")
        fig.update_layout(height=380, margin=dict(t=10, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Visões por dimensão")
    tabs = st.tabs([DIM_LABELS[d] for d in DIM_COLS])
    for tab, dim in zip(tabs, DIM_COLS):
        with tab:
            agg = analytics.budget_vs_actual(custos, orcamento, group_by=[dim])
            agg = agg.groupby(dim, as_index=False)[["realizado", "orcado", "desvio"]].sum()
            agg["desvio_pct"] = agg.apply(
                lambda r: r["desvio"] / r["orcado"] * 100 if r["orcado"] else None, axis=1)
            agg = agg.sort_values("realizado", ascending=False)
            col1, col2 = st.columns([1, 1])
            with col1:
                fig = px.pie(agg, names=dim, values="realizado", hole=0.45)
                fig.update_layout(height=320, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                st.dataframe(
                    style_desvio(agg.rename(columns={dim: DIM_LABELS[dim]}),
                                 ["realizado", "orcado", "desvio"], ["desvio_pct"]),
                    use_container_width=True, hide_index=True)


def page_budget(custos, orcamento, _forecast):
    st.title("🎯 Orçado vs Realizado")
    if custos.empty and orcamento.empty:
        st.info("Importe custos e orçamento na página **Importar Dados**.")
        return

    dims = st.multiselect("Abrir por", DIM_COLS, default=["provider"],
                          format_func=lambda d: DIM_LABELS[d])
    bva = analytics.budget_vs_actual(custos, orcamento, group_by=dims)

    total = bva.groupby("competencia", as_index=False)[["realizado", "orcado"]].sum()
    fig = go.Figure()
    fig.add_bar(x=total["competencia"], y=total["orcado"], name="Orçado",
                marker_color="#c7c7c7")
    fig.add_bar(x=total["competencia"], y=total["realizado"], name="Realizado",
                marker_color="#1f77b4")
    fig.update_layout(barmode="group", height=360, margin=dict(t=10, b=10),
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    if dims:
        st.subheader("Desvio por " + " + ".join(DIM_LABELS[d] for d in dims))
        agg = bva.groupby(dims, as_index=False)[["realizado", "orcado", "desvio"]].sum()
        agg["desvio_pct"] = agg.apply(
            lambda r: r["desvio"] / r["orcado"] * 100 if r["orcado"] else None, axis=1)
        agg["_label"] = agg[dims].agg(" | ".join, axis=1)
        agg = agg.sort_values("desvio", ascending=False)
        fig = px.bar(agg, x="desvio", y="_label", orientation="h",
                     color=agg["desvio"] > 0,
                     color_discrete_map={True: "#d62728", False: "#2ca02c"})
        fig.update_layout(height=max(300, 36 * len(agg)), showlegend=False,
                          yaxis_title="", xaxis_title="Desvio (R$) — positivo = estouro",
                          margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Tabela analítica")
    estouro = st.checkbox("Somente estouros (realizado > orçado)")
    tbl = bva[bva["desvio"] > 0] if estouro else bva
    st.dataframe(
        style_desvio(tbl.rename(columns=DIM_LABELS),
                     ["realizado", "orcado", "desvio"], ["desvio_pct"]),
        use_container_width=True, hide_index=True)
    st.download_button("⬇️ Exportar CSV", tbl.to_csv(index=False).encode("utf-8-sig"),
                       "orcado_vs_realizado.csv", "text/csv")


def page_rol(custos, _orcamento, receita):
    st.title("💵 Realizado vs RoL (Receita Operacional Líquida)")
    st.caption("Unit economics: quanto da receita o custo de tecnologia consome. "
               "Quanto **menor** o %, melhor a eficiência.")
    if custos.empty or receita.empty:
        st.info("Esta análise precisa de **custos** e **receita (ROL)** carregados — "
                "vá na página **Importar Dados**.")
        return

    visao = st.radio("Visão", ["Consolidado", "Por empresa"], horizontal=True)
    por_empresa = visao == "Por empresa"
    cvr = analytics.cost_vs_rol(custos, receita, por_empresa=por_empresa)
    cvr = cvr[cvr["rol"] > 0]

    if por_empresa:
        fig = px.line(cvr, x="competencia", y="pct_rol", color="empresa", markers=True)
        fig.update_layout(height=380, margin=dict(t=10, b=10),
                          yaxis=dict(ticksuffix="%", rangemode="tozero"),
                          yaxis_title="Custo / ROL", legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = go.Figure()
        fig.add_bar(x=cvr["competencia"], y=cvr["rol"], name="ROL",
                    marker_color="#c7e9c0")
        fig.add_bar(x=cvr["competencia"], y=cvr["realizado"], name="Custo realizado",
                    marker_color="#1f77b4")
        fig.add_scatter(x=cvr["competencia"], y=cvr["pct_rol"], name="% da ROL",
                        mode="lines+markers+text", yaxis="y2",
                        text=[f"{v:.1f}%" for v in cvr["pct_rol"]],
                        textposition="top center",
                        line=dict(color="#d62728"))
        fig.update_layout(
            barmode="group", height=400, margin=dict(t=30, b=10),
            legend=dict(orientation="h"),
            yaxis2=dict(overlaying="y", side="right", ticksuffix="%",
                        rangemode="tozero", showgrid=False))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Tabela analítica")
    tbl = cvr.rename(columns={"empresa": "Empresa", "rol": "ROL",
                              "realizado": "Custo realizado", "pct_rol": "Custo/ROL (%)"})
    sty = tbl.style.format(brl, subset=["Custo realizado", "ROL"]) \
        .format(lambda v: "—" if pd.isna(v) else f"{v:.2f}%", subset=["Custo/ROL (%)"])
    st.dataframe(sty, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Exportar CSV", cvr.to_csv(index=False).encode("utf-8-sig"),
                       "realizado_vs_rol.csv", "text/csv")


def page_anomalies(custos, *_):
    st.title("🚨 Anomalias de Consumo")
    if custos.empty:
        st.info("Importe custos na página **Importar Dados**.")
        return

    with st.expander("⚙️ Parâmetros de detecção"):
        c1, c2, c3 = st.columns(3)
        z = c1.slider("Sensibilidade diária (z-score)", 2.0, 5.0, 3.0, 0.5,
                      help="Menor = mais sensível. 3.0 é o padrão de mercado.")
        mom = c2.slider("Variação MoM mínima (%)", 10, 100, 30, 5)
        impacto = c3.number_input("Impacto mínimo MoM (R$)", 0, 100000, 500, 100)

    st.subheader("Picos diários (z-score robusto, janela móvel de 28 dias)")
    if anomalies.monthly_grain_share(custos) >= 0.8:
        st.info("📅 Esta base tem **grão mensal** (valor do mês distribuído pelos "
                "dias) — a análise de picos diários não se aplica e foi desativada. "
                "Use as **variações mês a mês** abaixo; quando os custos vierem "
                "com granularidade diária real (ex.: billing dos providers), os "
                "picos diários voltam automaticamente.")
        daily = anomalies.daily_anomalies(custos.iloc[0:0])
    else:
        daily = anomalies.all_dimension_daily(custos, z_threshold=z)
    if daily.empty:
        if anomalies.monthly_grain_share(custos) < 0.8:
            st.success("Nenhum pico diário detectado com os parâmetros atuais. ✅")
    else:
        st.dataframe(
            daily.assign(data=daily["data"].dt.strftime("%d/%m/%Y"))
            .style.format(brl, subset=["valor", "esperado", "desvio"])
            .format("{:.1f}", subset=["zscore"]),
            use_container_width=True, hide_index=True)

        sel = st.selectbox("Visualizar série", daily["serie"].unique())
        row = daily[daily["serie"] == sel].iloc[0]
        dims = row["dimensao"].split(" + ")
        df = custos.copy()
        df["serie"] = df[dims].agg(" | ".join, axis=1)
        serie = df[df["serie"] == sel].groupby("data", as_index=False)["valor"].sum()
        marks = daily[daily["serie"] == sel]
        fig = px.line(serie, x="data", y="valor")
        fig.add_scatter(x=marks["data"], y=marks["valor"], mode="markers",
                        marker=dict(color="#d62728", size=12, symbol="x"),
                        name="Anomalia")
        fig.update_layout(height=340, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Variações mês a mês (derivas estruturais)")
    momdf = anomalies.mom_anomalies(custos, pct_threshold=mom, min_impact=impacto)
    if momdf.empty:
        st.success("Nenhuma variação MoM acima do limiar. ✅")
    else:
        st.dataframe(
            momdf.style.format(brl, subset=["valor", "mes_anterior", "variacao"])
            .format(pct, subset=["variacao_pct"]),
            use_container_width=True, hide_index=True)


def page_import(*_):
    st.title("📥 Importar Dados")
    st.caption("Hoje: planilhas Excel. Amanhã: os mesmos dados podem chegar via "
               "API REST (`api.py`) — a validação é idêntica nos dois canais.")

    counts = db.row_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Linhas de custos", f"{counts['custos']:,}".replace(",", "."))
    c2.metric("Linhas de orçamento", f"{counts['orcamento']:,}".replace(",", "."))
    c3.metric("Linhas de receita (ROL)", f"{counts['receita']:,}".replace(",", "."))

    st.subheader("1 · Baixar templates")
    cols = st.columns(3)
    for col, (kind, label) in zip(cols, [("custos", "Custos (realizado)"),
                                         ("orcamento", "Orçamento"),
                                         ("receita", "Receita (ROL)")]):
        col.download_button(f"⬇️ Template — {label}", build_template(kind),
                            f"template_{kind}.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("2 · Enviar planilha")
    kind = st.radio("Tipo de dado", ["custos", "orcamento", "receita"],
                    format_func={"custos": "Custos (realizado)", "orcamento": "Orçamento",
                                 "receita": "Receita (ROL)"}.get, horizontal=True)
    file = st.file_uploader("Arquivo .xlsx ou .csv", type=["xlsx", "xls", "csv"])
    if file is not None:
        df = pd.read_csv(file) if file.name.lower().endswith(".csv") else \
            pd.read_excel(file, sheet_name=0)
        st.write(f"Pré-visualização ({len(df)} linhas):")
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)
        if st.button("✅ Importar", type="primary"):
            fn = {"custos": import_custos, "orcamento": import_orcamento,
                  "receita": import_receita}[kind]
            try:
                n, warns = fn(df, origem="excel")
                st.success(f"{n} linha(s) importada(s). Períodos reimportados foram "
                           "substituídos (sem duplicar).")
                for w in warns:
                    st.warning(w)
                st.cache_data.clear()
            except ValidationError as e:
                for p in e.problems:
                    st.error(p)

    st.subheader("3 · Dados de demonstração")
    col1, col2, col3 = st.columns(3)
    if col1.button("🧪 Demo 1 — sintética (substitui tudo)",
                   help="6 meses de dados fictícios com anomalias plantadas "
                        "para demonstrar a detecção."):
        res = load_demo()
        st.cache_data.clear()
        st.success(f"Demo 1 carregada: {res['custos']} custos, {res['orcamento']} "
                   f"orçamento, {res['receita']} receita (ROL).")
    if demo2_available():
        if col2.button("🏢 Demo 2 — TD Cloud 2025/26 (substitui tudo)",
                       help="Dados reais extraídos de 'TD Cloud 2025.xlsx': custos "
                            "2025 + 2026 jan-abr, orçamentos 2025 e 2026 e ROL 2026. "
                            "Grão mensal distribuído pelos dias do mês."):
            res = load_demo2()
            st.cache_data.clear()
            st.success(f"Demo 2 carregada: {res['custos']} custos, {res['orcamento']} "
                       f"orçamento, {res['receita']} receita (ROL).")
    else:
        col2.caption("Demo 2 indisponível: gere os CSVs com "
                     "`python tools/etl_td_cloud2025.py <planilha>`.")
    if col3.button("🗑️ Limpar toda a base"):
        db.clear_all()
        st.cache_data.clear()
        st.success("Base limpa.")


# ----------------------------------------------------------------- navegação
PAGES = {
    "📊 Visão Geral": page_overview,
    "🎯 Orçado vs Realizado": page_budget,
    "💵 Realizado vs RoL": page_rol,
    "🚨 Anomalias": page_anomalies,
    "📥 Importar Dados": page_import,
}

st.sidebar.title("💰 FinOps Analytics")
choice = st.sidebar.radio("Navegação", list(PAGES), label_visibility="collapsed")

custos, orcamento, receita = load_data()
if choice != "📥 Importar Dados":
    custos, orcamento, receita = apply_filters(custos, orcamento, receita)

PAGES[choice](custos, orcamento, receita)

st.sidebar.divider()
st.sidebar.caption(f"Base: `finops.db` · Atualizado em {date.today():%d/%m/%Y}")
