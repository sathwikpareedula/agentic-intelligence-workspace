"""Deterministic north-star August sales reporting workflow."""

from dataclasses import dataclass
import re

import pandas as pd

from app.models.grades import PolicyEvidence
from app.models.transformations import JoinSpec
from app.services.artifacts import GeneratedArtifact, generate_sales_management_workbook
from app.services.transformations import JoinDiagnostics, join_datasets


class SalesReportError(Exception):
    """Raised when report inputs or policy evidence are insufficient."""


@dataclass(frozen=True)
class SalesReportResult:
    cleaned_transactions: pd.DataFrame
    regional_performance: pd.DataFrame
    commissions: pd.DataFrame
    join_diagnostics: JoinDiagnostics
    commission_rate: float
    citations: list
    artifact: GeneratedArtifact


def build_august_sales_report(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    targets: pd.DataFrame,
    policy_evidence: list[PolicyEvidence],
) -> SalesReportResult:
    _require(transactions, {"transaction_id", "date", "salesperson", "customer_id", "amount", "discount", "status"}, "transactions")
    _require(customers, {"customer_id", "region"}, "customers")
    _require(targets, {"region", "target"}, "targets")
    rates = set()
    citations = []
    pattern = re.compile(r"commission rate(?: of| is)?\s*(\d+(?:\.\d+)?)\s*%", re.I)
    for evidence in policy_evidence:
        found = pattern.findall(evidence.text)
        if found:
            rates.update(float(value) for value in found)
            citations.append(evidence.source)
    if not rates:
        raise SalesReportError("Commission policy evidence does not establish a commission rate.")
    if len(rates) > 1:
        raise SalesReportError("Commission policy evidence contains conflicting rates.")
    rate = next(iter(rates)) / 100
    if not 0 <= rate <= 1:
        raise SalesReportError("Commission rate must be between 0 and 100 percent.")

    cleaned = transactions.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce")
    cleaned["amount"] = pd.to_numeric(cleaned["amount"], errors="coerce")
    cleaned["discount"] = pd.to_numeric(cleaned["discount"], errors="coerce").fillna(0)
    cleaned = cleaned[
        cleaned["status"].astype(str).str.lower().eq("complete")
        & cleaned["date"].dt.month.eq(8)
        & cleaned["amount"].notna()
    ].drop_duplicates(subset=["transaction_id"], keep="first")
    if ((cleaned["discount"] < 0) | (cleaned["amount"] < cleaned["discount"])).any():
        raise SalesReportError("Amounts and discounts contain invalid values.")
    cleaned["net_sales"] = cleaned["amount"] - cleaned["discount"]
    cleaned["commission"] = cleaned["net_sales"] * rate

    joined = join_datasets(cleaned, customers[["customer_id", "region"]], JoinSpec(left_on=["customer_id"], right_on=["customer_id"], how="left"))
    regional = joined.frame.groupby("region", dropna=False, as_index=False)["net_sales"].sum()
    regional = regional[regional["region"].notna()].merge(targets[["region", "target"]], how="outer", on="region")
    regional[["net_sales", "target"]] = regional[["net_sales", "target"]].fillna(0)
    regional["variance"] = regional["net_sales"] - regional["target"]
    regional["attainment_pct"] = regional.apply(lambda row: row["net_sales"] / row["target"] * 100 if row["target"] else None, axis=1)
    regional["underperformance"] = (-regional["variance"]).clip(lower=0)
    regional = regional.sort_values(["underperformance", "region"], ascending=[False, True], kind="stable").reset_index(drop=True)
    commissions = cleaned.groupby("salesperson", as_index=False).agg(net_sales=("net_sales", "sum"), commission=("commission", "sum"))
    commissions = commissions.sort_values("salesperson", kind="stable").reset_index(drop=True)

    artifact = generate_sales_management_workbook(
        cleaned,
        regional,
        commissions,
        provenance={
            "transactions": "preserved; report operates on an in-memory copy",
            "commission_policy_sources": ",".join(str(source.chunk_id) for source in citations),
            "commission_rate": f"{rate * 100:g}%",
        },
    )
    return SalesReportResult(cleaned, regional, commissions, joined.diagnostics, rate, citations, artifact)


def _require(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise SalesReportError(f"{label.title()} data is missing required column(s): {', '.join(missing)}.")
