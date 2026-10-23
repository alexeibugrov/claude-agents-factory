"""Code prefilters: cheap, deterministic, operator-owned criteria on structured fields (plan D7).

They run after storage and before the screener, to save subscription capacity. Every rule is off
while its threshold is null; the operator sets and tightens thresholds in ``agent_config.yaml``.
Anything that needs judgement (tech fit, scope, red flags) belongs in the screener prompt, not here.
A job with an unknown value for a rule's field passes that rule — absence is not evidence.
"""

from __future__ import annotations

from typing import Any


def prefilter_reason(job: dict[str, Any], rules: dict[str, Any]) -> str | None:
    """Return the first failing rule as ``"<rule>: <detail>"``, or None if the job passes."""

    def active(key: str) -> bool:
        return rules.get(key) is not None

    if active("require_payment_verified") and rules["require_payment_verified"]:
        if job.get("client_payment_verified") is False:
            return "require_payment_verified: client payment not verified"
    if active("min_client_total_spent"):
        spent = job.get("client_total_spent")
        if spent is not None and float(spent) < float(rules["min_client_total_spent"]):
            return f"min_client_total_spent: {spent} < {rules['min_client_total_spent']}"
    if active("min_client_rating"):
        rating = job.get("client_rating")
        if rating is not None and float(rating) < float(rules["min_client_rating"]):
            return f"min_client_rating: {rating} < {rules['min_client_rating']}"
    if active("min_client_review_count"):
        reviews = job.get("client_review_count")
        if reviews is not None and int(reviews) < int(rules["min_client_review_count"]):
            return f"min_client_review_count: {reviews} < {rules['min_client_review_count']}"
    if active("max_total_applicants"):
        applicants = job.get("total_applicants")
        if applicants is not None and int(applicants) > int(rules["max_total_applicants"]):
            return f"max_total_applicants: {applicants} > {rules['max_total_applicants']}"
    if active("job_types"):
        allowed = {str(t).upper() for t in rules["job_types"]}
        job_type = job.get("job_type")
        if job_type and str(job_type).upper() not in allowed:
            return f"job_types: {job_type} not in {sorted(allowed)}"
    if active("min_hourly_rate") and str(job.get("job_type") or "").upper() == "HOURLY":
        top = job.get("hourly_budget_max") or job.get("hourly_budget_min")
        if top is not None and float(top) < float(rules["min_hourly_rate"]):
            return f"min_hourly_rate: {top} < {rules['min_hourly_rate']}"
    if active("min_fixed_budget") and str(job.get("job_type") or "").upper() == "FIXED":
        budget = job.get("budget_amount")
        if budget is not None and float(budget) < float(rules["min_fixed_budget"]):
            return f"min_fixed_budget: {budget} < {rules['min_fixed_budget']}"
    if active("exclude_client_country_codes"):
        excluded = {str(c).upper() for c in rules["exclude_client_country_codes"]}
        code = job.get("client_country_code")
        if code and str(code).upper() in excluded:
            return f"exclude_client_country_codes: {code}"
    if active("include_client_country_codes"):
        allowed = {str(c).upper() for c in rules["include_client_country_codes"]}
        code = job.get("client_country_code")
        if code and str(code).upper() not in allowed:
            return f"include_client_country_codes: {code} not in allowed regions"
    return None
