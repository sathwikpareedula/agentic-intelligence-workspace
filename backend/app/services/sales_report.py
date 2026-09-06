"""Deterministic, policy-grounded August sales reporting workflow."""

from dataclasses import dataclass
import re
from math import isfinite
from typing import Any

import pandas as pd

from app.models.grades import PolicyEvidence
from app.models.transformations import JoinSpec
from app.services.artifacts import GeneratedArtifact, generate_sales_management_workbook
from app.services.transformations import JoinDiagnostics, join_datasets


class SalesReportError(Exception):
    """Raised when report inputs or policy evidence are insufficient."""

    def __init__(self, message: str, status: str = "failed") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SalesReportResult:
    cleaned_transactions: pd.DataFrame
    regional_performance: pd.DataFrame
    commissions: pd.DataFrame
    join_diagnostics: JoinDiagnostics
    target_join_diagnostics: dict[str, int]
    data_quality: dict[str, Any]
    commission_rate: float
    citations: list
    warnings: list[str]
    verification_facts: dict[str, float]
    artifact: GeneratedArtifact


def build_august_sales_report(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    targets: pd.DataFrame,
    policy_evidence: list[PolicyEvidence],
    *,
    source_names: dict[str, str] | None = None,
) -> SalesReportResult:
    """Build the report without mutating source frames or delegating arithmetic to a model."""

    _require(
        transactions,
        {"transaction_id", "date", "salesperson", "customer_id", "amount", "discount", "status"},
        "transactions",
    )
    _require(customers, {"customer_id", "region"}, "customers")
    _require(targets, {"region", "target"}, "targets")
    rate, citations = _commission_rate(policy_evidence)

    cleaned, quality = _clean_transactions(transactions)
    cleaned["commission"] = cleaned["net_sales"] * rate
    clean_customers, customer_warnings = _clean_customers(customers)
    clean_targets = _clean_targets(targets)

    joined = join_datasets(
        cleaned,
        clean_customers[["customer_id", "region"]],
        JoinSpec(left_on=["customer_id"], right_on=["customer_id"], how="left"),
    )
    if joined.diagnostics.many_to_many_detected or joined.diagnostics.row_multiplication_occurred:
        raise SalesReportError(
            "Customer join would multiply transaction rows; customer_id must map to at most one region."
        )

    warnings = list(customer_warnings)
    if joined.diagnostics.left_unmatched_rows:
        warnings.append(
            f"{joined.diagnostics.left_unmatched_rows} cleaned transaction row(s) had no matching customer; "
            "their sales remain visible under Unassigned and still contribute to salesperson commissions."
        )

    joined_frame = joined.frame.copy()
    joined_frame["region"] = joined_frame["region"].fillna("Unassigned")
    cleaned_output = joined_frame[
        [
            "transaction_id",
            "date",
            "salesperson",
            "customer_id",
            "region",
            "amount",
            "discount",
            "net_sales",
            "commission",
            "status",
        ]
    ].copy()
    for column in transactions.columns:
        if column not in cleaned_output.columns and column in joined_frame.columns:
            cleaned_output[column] = joined_frame[column]

    actuals = joined_frame.groupby("region", dropna=False, as_index=False).agg(
        transaction_count=("transaction_id", "count"),
        net_sales=("net_sales", "sum"),
    )
    regional = actuals.merge(clean_targets, how="outer", on="region", indicator=True, validate="one_to_one")
    target_diagnostics = {
        "actual_regions": int(len(actuals)),
        "target_regions": int(len(clean_targets)),
        "matched_regions": int((regional["_merge"] == "both").sum()),
        "regions_missing_targets": int((regional["_merge"] == "left_only").sum()),
        "targets_without_sales": int((regional["_merge"] == "right_only").sum()),
    }
    if target_diagnostics["regions_missing_targets"]:
        warnings.append(
            f"{target_diagnostics['regions_missing_targets']} region(s) with sales had no target; "
            "variance and attainment remain unreported for those rows."
        )
    if target_diagnostics["targets_without_sales"]:
        warnings.append(
            f"{target_diagnostics['targets_without_sales']} target region(s) had no completed August sales."
        )

    regional["transaction_count"] = regional["transaction_count"].fillna(0).astype(int)
    regional["net_sales"] = regional["net_sales"].fillna(0.0)
    regional["variance"] = regional["net_sales"] - regional["target"]
    regional["attainment_pct"] = regional["net_sales"].div(regional["target"]).mul(100)
    regional.loc[regional["target"].eq(0), "attainment_pct"] = pd.NA
    regional["underperformance"] = (-regional["variance"]).clip(lower=0)
    regional["performance_status"] = regional.apply(_performance_status, axis=1)
    regional = regional.drop(columns=["_merge"]).sort_values(
        ["underperformance", "region"], ascending=[False, True], na_position="last", kind="stable"
    ).reset_index(drop=True)
    shortfall_total = float(regional["underperformance"].sum())
    regional["share_of_shortfall_pct"] = regional["underperformance"] / shortfall_total * 100 if shortfall_total else 0.0

    commissions = joined_frame.groupby("salesperson", as_index=False).agg(
        transaction_count=("transaction_id", "count"),
        net_sales=("net_sales", "sum"),
        commission=("commission", "sum"),
    )
    total_sales = float(commissions["net_sales"].sum())
    total_commission = float(commissions["commission"].sum())
    commissions["share_of_sales_pct"] = commissions["net_sales"].div(total_sales).mul(100) if total_sales else 0.0
    commissions = commissions.sort_values(["net_sales", "salesperson"], ascending=[False, True], kind="stable").reset_index(drop=True)

    facts: dict[str, float] = {
        "total.net_sales": total_sales,
        "total.commission": total_commission,
    }
    for row in regional.itertuples(index=False):
        facts[f"regional.{row.region}.net_sales"] = float(row.net_sales)
        if pd.notna(row.target):
            facts[f"regional.{row.region}.target"] = float(row.target)
            facts[f"regional.{row.region}.variance"] = float(row.variance)
            facts[f"regional.{row.region}.underperformance"] = float(row.underperformance)
    for row in commissions.itertuples(index=False):
        facts[f"salesperson.{row.salesperson}.net_sales"] = float(row.net_sales)
        facts[f"commission.{row.salesperson}"] = float(row.commission)

    targeted = regional[regional["target"].notna()]
    if not targeted.empty:
        largest = targeted.sort_values(
            ["underperformance", "region"], ascending=[False, True], kind="stable"
        ).iloc[0]
        facts["regional.largest_underperformance"] = float(largest["underperformance"])

    quality.update(
        {
            "cleaned_rows": int(len(cleaned_output)),
            "customer_unmatched_rows": joined.diagnostics.left_unmatched_rows,
            **target_diagnostics,
        }
    )
    artifact = generate_sales_management_workbook(
        cleaned_output,
        regional,
        commissions,
        data_quality=quality,
        customer_join_diagnostics=joined.diagnostics,
        target_join_diagnostics=target_diagnostics,
        citations=citations,
        provenance={
            "transactions_source": (source_names or {}).get("transactions", "uploaded transactions"),
            "customers_source": (source_names or {}).get("customers", "uploaded customers"),
            "targets_source": (source_names or {}).get("targets", "uploaded targets"),
            "source_preservation": "Original uploads were read only; all cleaning and calculations used in-memory copies.",
            "commission_policy_sources": ",".join(str(source.chunk_id) for source in citations),
            "commission_rate": f"{rate * 100:g}% of completed August net sales after discounts",
            "calculation_boundary": "All workbook values were computed by deterministic typed code, not by a language model.",
        },
        warnings=warnings,
    )
    return SalesReportResult(
        cleaned_output,
        regional,
        commissions,
        joined.diagnostics,
        target_diagnostics,
        quality,
        rate,
        citations,
        warnings,
        facts,
        artifact,
    )


def _commission_rate(policy_evidence: list[PolicyEvidence]) -> tuple[float, list]:
    rates: set[float] = set()
    citations = []
    pattern = re.compile(r"commission rate(?: of| is)?\s*(\d+(?:\.\d+)?)\s*%", re.I)
    for evidence in policy_evidence:
        found = pattern.findall(evidence.text)
        if found:
            rates.update(float(value) for value in found)
            citations.append(evidence.source)
    if not rates:
        raise SalesReportError("Commission policy evidence does not establish a commission rate.", "insufficient_evidence")
    if len(rates) > 1:
        raise SalesReportError("Commission policy evidence contains conflicting rates.", "conflicting_evidence")
    # Fail closed on qualifiers, exceptions, gross-sales rules and document instructions.
    # This is a deliberately small supported policy language, not a general policy interpreter.
    supported = re.compile(
        r"(?:August commission policy:\s*)?Salespeople earn a commission rate(?: of| is)?\s*"
        r"\d+(?:\.\d+)?\s*% of completed net sales after discounts\.?", re.I
    )
    if any(not supported.fullmatch(" ".join(item.text.split())) for item in policy_evidence):
        raise SalesReportError(
            "Unsupported or ambiguous commission policy: require one flat rate of completed net sales after discounts, without exceptions.",
            "insufficient_evidence",
        )
    rate = next(iter(rates)) / 100
    if not 0 <= rate <= 1:
        raise SalesReportError("Commission rate must be between 0 and 100 percent.")
    return rate, list({str(source.chunk_id): source for source in citations}.values())


def _clean_transactions(transactions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    cleaned = transactions.copy(deep=True)
    original_rows = len(cleaned)
    if {"net_sales", "commission", "region"} & set(transactions.columns):
        raise SalesReportError("Transactions contain reserved report output columns; rename them explicitly before running the recipe.")
    for column in ("transaction_id", "salesperson", "customer_id", "status"):
        cleaned[column] = cleaned[column].map(lambda value: value.strip() if isinstance(value, str) else value)
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce")
    cleaned["amount"] = pd.to_numeric(cleaned["amount"], errors="coerce")
    missing_discounts = int(cleaned["discount"].isna().sum())
    parsed_discounts = pd.to_numeric(cleaned["discount"], errors="coerce")
    invalid_discounts = cleaned["discount"].notna() & parsed_discounts.isna()
    if invalid_discounts.any():
        raise SalesReportError("Discount values must be numeric when provided; invalid discounts cannot be assumed to be zero.")
    if any(not isfinite(float(value)) for value in cleaned["amount"].dropna()) or any(
        not isfinite(float(value)) for value in parsed_discounts.dropna()
    ):
        raise SalesReportError("Amounts and discounts must be finite numbers.")
    cleaned["discount"] = parsed_discounts.fillna(0.0)
    status_complete = cleaned["status"].astype(str).str.strip().str.lower().eq("complete")
    valid_august = cleaned["date"].notna() & cleaned["date"].dt.month.eq(8)
    valid_amount = cleaned["amount"].notna()
    identity_columns = ["transaction_id", "salesperson", "customer_id"]
    valid_identity = pd.Series(True, index=cleaned.index)
    for column in identity_columns:
        valid_identity &= cleaned[column].notna() & cleaned[column].astype(str).str.strip().ne("")

    duplicate_rows = cleaned[cleaned["transaction_id"].duplicated(keep=False)]
    for transaction_id, group in duplicate_rows.groupby("transaction_id", dropna=False):
        if len(group.drop_duplicates()) > 1:
            raise SalesReportError(
                f"Transaction ID '{transaction_id}' has conflicting duplicate rows; automatic deduplication is unsafe."
            )

    eligible = status_complete & valid_august & valid_amount & valid_identity
    cleaned = cleaned.loc[eligible].drop_duplicates(subset=["transaction_id"], keep="first").copy()
    august_years = cleaned["date"].dt.year.dropna().unique()
    if len(august_years) > 1:
        raise SalesReportError("Completed transactions span multiple August years; the reporting year is ambiguous.")
    if ((cleaned["discount"] < 0) | (cleaned["amount"] < cleaned["discount"])).any():
        raise SalesReportError("Amounts and discounts contain invalid values.")
    if cleaned.empty:
        raise SalesReportError("No valid completed August transactions remain after bounded cleaning.")
    cleaned["net_sales"] = cleaned["amount"] - cleaned["discount"]
    cleaned["commission"] = pd.NA
    for column in ("transaction_id", "salesperson", "customer_id", "status"):
        cleaned[column] = cleaned[column].astype(str).str.strip()

    quality = {
        "original_transaction_rows": int(original_rows),
        "non_complete_rows_excluded": int((~status_complete).sum()),
        "invalid_or_non_august_date_rows_excluded": int((~valid_august).sum()),
        "invalid_amount_rows_excluded": int((~valid_amount).sum()),
        "missing_identity_rows_excluded": int((~valid_identity).sum()),
        "duplicate_transaction_rows_removed": int(eligible.sum() - len(cleaned)),
        "missing_discounts_filled_with_zero": missing_discounts,
    }
    return cleaned, quality


def _clean_customers(customers: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    result = customers[["customer_id", "region"]].copy(deep=True)
    if result[["customer_id", "region"]].isna().any(axis=None):
        raise SalesReportError("Customer data contains missing customer_id or region values.")
    result["customer_id"] = result["customer_id"].astype(str).str.strip()
    result["region"] = result["region"].astype(str).str.strip()
    if result["customer_id"].eq("").any() or result["region"].eq("").any():
        raise SalesReportError("Customer data contains blank customer_id or region values.")
    warnings = []
    repeated = result[result["customer_id"].duplicated(keep=False)]
    for customer_id, group in repeated.groupby("customer_id"):
        if group["region"].nunique(dropna=False) > 1:
            raise SalesReportError(f"Customer ID '{customer_id}' maps to conflicting regions.")
    before = len(result)
    result = result.drop_duplicates(subset=["customer_id"], keep="first")
    if before != len(result):
        warnings.append(f"Removed {before - len(result)} duplicate customer row(s) with identical region mappings.")
    return result, warnings


def _clean_targets(targets: pd.DataFrame) -> pd.DataFrame:
    result = targets[["region", "target"]].copy(deep=True)
    if result["region"].isna().any():
        raise SalesReportError("Target data contains missing or invalid region/target values.")
    result["region"] = result["region"].astype(str).str.strip()
    result["target"] = pd.to_numeric(result["target"], errors="coerce")
    if result["region"].eq("").any() or result["target"].isna().any():
        raise SalesReportError("Target data contains missing or invalid region/target values.")
    if result["region"].duplicated().any():
        raise SalesReportError("Target data contains duplicate regions; one target per region is required.")
    if not all(isfinite(float(value)) for value in result["target"]):
        raise SalesReportError("Regional targets must be finite numbers.")
    if (result["target"] < 0).any():
        raise SalesReportError("Regional targets cannot be negative.")
    return result


def _performance_status(row: pd.Series) -> str:
    if pd.isna(row["target"]):
        return "Target missing"
    if row["variance"] < 0:
        return "Under target"
    if row["variance"] > 0:
        return "Over target"
    return "On target"


def _require(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise SalesReportError(f"{label.title()} data is missing required column(s): {', '.join(missing)}.")
