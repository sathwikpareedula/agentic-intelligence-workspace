# Agentic Intelligence Workspace

**Turn recurring data work into verified, reusable workflows.**

Agentic Intelligence Workspace is an agentic data-operations platform that combines AI planning with deterministic data tools to analyze structured data and business documents, generate validated deliverables, preserve evidence and provenance, and safely rerun successful workflows on new data.

Instead of asking an AI assistant to repeat the same analysis every month, the workspace turns a successful task into a versioned workflow that can be rerun, inspected, compared, and stopped when new inputs are no longer safe or compatible.

---

## Why I Built This

General-purpose AI assistants are already good at one-off spreadsheet analysis.

The harder engineering problem is making recurring AI-assisted data work:

- reproducible;
- verifiable;
- evidence-backed;
- safe around changing inputs;
- deterministic where correctness matters;
- inspectable after execution;
- reusable across future reporting periods.

The core design principle is:

> **Use the model for planning and semantic reasoning. Use deterministic tools for calculations, transformations, validation, and artifact generation.**

The model can choose from approved tools and explain results, but it cannot execute arbitrary Python, shell commands, or unrestricted SQL.

---

## Flagship Demo: Reusable Monthly Sales Workflow

The main demo shows the full lifecycle of a recurring analytical workflow.

### First run

Upload:

- `sample_data/august_transactions.csv`
- `sample_data/sales_customers.csv`
- `sample_data/sales_targets.csv`
- `sample_data/commission_policy.pdf`

The system:

1. inspects the uploaded datasets;
2. identifies their roles from their schemas;
3. retrieves the relevant commission policy evidence;
4. cleans and joins the data;
5. calculates sales, targets, shortfalls, and commissions using deterministic code;
6. verifies important numeric and policy-backed claims;
7. generates a management workbook;
8. records provenance and execution history;
9. saves the successful operation as a reusable workflow.

The generated workbook contains:

- Executive Summary
- Regional Performance
- Salesperson Performance
- Cleaned Transactions
- Data Quality
- Provenance & Sources

It also contains charts for actual vs. target sales, shortfalls, and commissions.

### Run it again

Replace only the transactions file with:

```text
sample_data/september_transactions.csv
