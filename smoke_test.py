"""Teste rápido do pipeline: carga demo → análises → anomalias."""

from finops import analytics, anomalies, db
from finops.sample_data import load_demo

res = load_demo()
print("Carga demo:", res)

custos = db.read_table("custos")
orc = db.read_table("orcamento")
rec = db.read_table("receita")

bva = analytics.budget_vs_actual(custos, orc, group_by=["provider"])
print("\nOrçado vs Realizado (por provider) — últimas linhas:")
print(bva.tail(4).to_string(index=False))

cvr = analytics.cost_vs_rol(custos, rec)
print("\nRealizado vs RoL (custo como % da receita) — consolidado:")
print(cvr.to_string(index=False))

cvr_emp = analytics.cost_vs_rol(custos, rec, por_empresa=True)
print("\nRealizado vs RoL — por empresa (últimas linhas):")
print(cvr_emp.tail(4).to_string(index=False))

comp = custos["data"].max().strftime("%Y-%m")
print("\nRun-rate", comp, "->", analytics.run_rate(custos, comp))
print("KPI Custo/ROL:", analytics.pct_rol_kpi(custos, rec, comp))
print("Cobertura de alocação:", analytics.allocation_coverage(custos))

daily = anomalies.all_dimension_daily(custos)
print(f"\nAnomalias diárias detectadas: {len(daily)}")
print(daily.head(4).to_string(index=False))

mom = anomalies.mom_anomalies(custos)
print(f"\nAnomalias MoM detectadas: {len(mom)}")
print(mom.head(4).to_string(index=False))
