"""Strict deterministic rule engine."""

from __future__ import annotations

from job_automation.config.loader import SearchConfig
from job_automation.models.domain import Decision, Evidence, NormalizedJob


class RuleEngine:
    def __init__(self, config: SearchConfig):
        self.config = config

    def decide(self, job: NormalizedJob) -> NormalizedJob:
        if job.is_duplicate or job.decision == Decision.DUPLICATE:
            return job

        # Keep early forced decisions (e.g. banned industry/company from portal card).
        if job.decision in {Decision.REJECTED, Decision.NEEDS_REVIEW} and job.decision_reason:
            return job

        reject_reason = self._check_hard_rejects(job)
        if reject_reason:
            job.decision = Decision.REJECTED
            job.decision_reason = reject_reason
            job.evidence.append(
                Evidence(field="decision", value="rejected", evidence_text=reject_reason)
            )
            return job

        review_reason = self._check_needs_review(job)
        if review_reason:
            job.decision = Decision.NEEDS_REVIEW
            job.decision_reason = review_reason
            job.evidence.append(
                Evidence(field="decision", value="needs_review", evidence_text=review_reason)
            )
            return job

        if self._is_eligible(job):
            job.decision = Decision.ELIGIBLE
            job.decision_reason = (
                "Fully remote US role, no travel, no clearance, salary meets minimum, "
                "and role/skills match."
            )
            job.evidence.append(
                Evidence(field="decision", value="eligible", evidence_text=job.decision_reason)
            )
            return job

        job.decision = Decision.NEEDS_REVIEW
        job.decision_reason = "Not all strict eligibility requirements are clearly satisfied."
        job.evidence.append(
            Evidence(field="decision", value="needs_review", evidence_text=job.decision_reason)
        )
        return job

    def _check_hard_rejects(self, job: NormalizedJob) -> str | None:
        banned_hit = self._banned_industry_hit(job.industry)
        if banned_hit:
            return f"Banned industry: {banned_hit}"
        if job.role_excluded:
            return "Role is excluded"
        if job.security_clearance_required is True:
            return "Security clearance required"
        if job.travel_required is True:
            return "Travel required"
        if job.remote_policy in {"onsite_required", "hybrid_required"}:
            return f"Remote policy rejected: {job.remote_policy}"
        if job.industry == "government":
            return "Government industry"
        if job.role_match is False:
            return "Role does not match target roles"
        if job.skill_match is False:
            return "Skills do not match target skills"
        if job.commitment and job.commitment not in self.config.commitment_types:
            return f"Commitment not allowed: {job.commitment}"
        if job.experience_level and job.experience_level not in self.config.experience_levels:
            return f"Experience level not allowed: {job.experience_level}"

        salary_reject = self._salary_reject_reason(job)
        if salary_reject:
            return salary_reject
        return None

    def _check_needs_review(self, job: NormalizedJob) -> str | None:
        apply_review = self._apply_link_review_reason(job.apply_url)
        if apply_review:
            return apply_review
        if job.skill_match is None:
            return "Skills partially match target skills"
        if not job.description_text:
            return "Job description missing"
        if job.salary_text is None and job.salary_min_annual is None and job.salary_min_hourly is None:
            return "Salary missing"
        if job.remote_policy in {"remote_unclear", "remote_specific_states", "hybrid_possible_remote"}:
            return f"Remote policy needs review: {job.remote_policy}"
        if job.travel_required is None:
            return "Travel requirement unclear"
        if job.security_clearance_required is None:
            return "Security clearance requirement unclear"
        if job.security_related_company_or_role:
            return "Security/cybersecurity related company or role"
        if job.commitment is None:
            return "Commitment unclear"
        if job.experience_level is None:
            return "Experience level unclear"
        return None

    def _apply_link_review_reason(self, apply_url: str | None) -> str | None:
        if not apply_url or not str(apply_url).strip():
            return "apply link error"
        normalized = str(apply_url).strip().lower()
        # Built In Easy Apply paths look like /apply/job/<id>
        if "/apply/job/" in normalized:
            return "easy apply"
        return None

    def _banned_industry_hit(self, industry: str | None) -> str | None:
        if not industry:
            return None
        text = industry.lower()
        for term in self.config.banned_industry_terms:
            token = term.lower().strip()
            if token and token in text:
                return term
        return None

    def _is_eligible(self, job: NormalizedJob) -> bool:
        return all(
            [
                job.role_match is True,
                not job.role_excluded,
                job.skill_match is True,
                job.remote_policy == "fully_remote_us",
                job.travel_required is False,
                job.security_clearance_required is False,
                job.industry != "government",
                not job.security_related_company_or_role,
                job.salary_text is not None
                or job.salary_min_annual is not None
                or job.salary_min_hourly is not None,
                self._salary_meets_minimum(job),
                job.commitment in self.config.commitment_types,
                job.experience_level in self.config.experience_levels,
            ]
        )

    def _salary_reject_reason(self, job: NormalizedJob) -> str | None:
        if job.salary_min_annual is not None and job.salary_min_annual < self.config.salary.min_annual:
            return "Salary below minimum annual threshold"
        if job.salary_min_hourly is not None and job.salary_min_hourly < self.config.salary.min_hourly:
            return "Salary below minimum hourly threshold"
        return None

    def _salary_meets_minimum(self, job: NormalizedJob) -> bool:
        if job.salary_min_annual is not None:
            return job.salary_min_annual >= self.config.salary.min_annual
        if job.salary_min_hourly is not None:
            return job.salary_min_hourly >= self.config.salary.min_hourly
        return False
