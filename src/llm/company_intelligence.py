from typing import List, Dict, Any, Optional
from collections import Counter
import json
import logging

from src.db.models import Company, Job, JobAnalysis
from src.llm.client import LLMClient
from src.db.repositories import JobRepository, CompanyIntelligenceRepository

logger = logging.getLogger(__name__)


class CompanyIntelligenceAnalyzer:
    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    async def analyze_job_posting(
        self, 
        job_text: str, 
        company_name: str, 
        profile
    ) -> Dict[str, Any]:
        """Analyze a single job posting for application strategy"""
        return await self.llm.analyze_job_for_application(
            job_text, company_name, {}, self._profile_to_text(profile)
        )

    async def aggregate_company_intelligence(
        self, 
        company: Company, 
        jobs: List[Job]
    ) -> Dict[str, Any]:
        """Aggregate intelligence from all job postings for a company"""
        if not jobs:
            return {"error": "No jobs found for company"}

        # Prepare job texts for LLM analysis
        job_texts = []
        for job in jobs:
            text_parts = []
            if job.title:
                text_parts.append(f"Title: {job.title}")
            if job.description:
                text_parts.append(job.description[:3000])
            if job.requirements:
                text_parts.append(f"Requirements: {job.requirements[:1000]}")
            if job.benefits:
                text_parts.append(f"Benefits: {job.benefits[:500]}")
            if job.salary_range:
                text_parts.append(f"Salary: {job.salary_range}")
            job_texts.append("\n".join(text_parts))

        # Get LLM analysis
        llm_analysis = await self.llm.analyze_company_intelligence(
            company.name, job_texts, ""
        )

        # Local aggregation from structured data
        local_analysis = self._aggregate_locally(jobs)

        # Merge both
        return {**local_analysis, **llm_analysis}

    def _aggregate_locally(self, jobs: List[Job]) -> Dict[str, Any]:
        """Aggregate using structured database fields"""
        all_skills = []
        all_tech = []
        positions = []
        locations = []
        remote_policies = []
        seniorities = []
        salary_ranges = []

        for job in jobs:
            if job.extracted_skills:
                all_skills.extend(job.extracted_skills)
            if job.extracted_tech:
                all_tech.extend(job.extracted_tech)
            if job.title:
                positions.append(job.title)
            if job.location:
                locations.append(job.location)
            if job.remote_policy:
                remote_policies.append(job.remote_policy)
            if job.experience_level:
                seniorities.append(job.experience_level)
            if job.salary_range:
                salary_ranges.append(job.salary_range)

        # Analyze problems from analyses
        all_problems = []
        for job in jobs:
            for analysis in job.analyses:
                if analysis.key_requirements:
                    all_problems.extend(analysis.key_requirements)

        return {
            "local_skills_frequency": dict(Counter(all_skills).most_common(20)),
            "local_tech_frequency": dict(Counter(all_tech).most_common(20)),
            "position_frequency": dict(Counter(positions).most_common(15)),
            "location_distribution": dict(Counter(locations).most_common(10)),
            "remote_policy_distribution": dict(Counter(remote_policies)),
            "seniority_distribution": dict(Counter(seniorities)),
            "total_jobs_analyzed": len(jobs),
            "relevant_jobs": sum(1 for j in jobs if j.relevance_score >= 0.7),
        }

    def _profile_to_text(self, profile) -> str:
        parts = []
        if hasattr(profile, 'current_role') and profile.current_role:
            parts.append(f"Current Role: {profile.current_role}")
        if hasattr(profile, 'years_experience') and profile.years_experience:
            parts.append(f"Experience: {profile.years_experience} years")
        if hasattr(profile, 'skills') and profile.skills:
            parts.append(f"Skills: {', '.join(profile.skills)}")
        if hasattr(profile, 'tech_stack') and profile.tech_stack:
            parts.append(f"Tech: {', '.join(profile.tech_stack)}")
        if hasattr(profile, 'preferred_roles') and profile.preferred_roles:
            parts.append(f"Target Roles: {', '.join(profile.preferred_roles)}")
        if hasattr(profile, 'remote_preference') and profile.remote_preference:
            parts.append(f"Remote: {profile.remote_preference}")
        if hasattr(profile, 'visa_sponsorship_needed') and profile.visa_sponsorship_needed:
            parts.append("NEEDS VISA SPONSORSHIP")
        return "\n".join(parts) if parts else "No profile"


class CompanyIntelligenceService:
    """High-level service for company intelligence operations"""
    
    def __init__(self):
        self.analyzer = CompanyIntelligenceAnalyzer()

    async def refresh_company_intelligence(self, company_id: int) -> Dict[str, Any]:
        """Refresh intelligence for a specific company"""
        from src.db.database import db
        from src.db.repositories import CompanyRepository, JobRepository, CompanyIntelligenceRepository
        
        async with db.session() as session:
            company_repo = CompanyRepository(session)
            company = await company_repo.get_by_id(company_id)
            
            if not company:
                return {"error": "Company not found"}
            
            job_repo = JobRepository(session)
            jobs = await job_repo.get_company_jobs(company_id)
            
            intelligence = await self.analyzer.aggregate_company_intelligence(company, jobs)
            
            # Store in database
            intel_repo = CompanyIntelligenceRepository(session)
            await intel_repo.update_intelligence(company_id, **intelligence)
            
            return intelligence

    async def get_top_companies_report(self, limit: int = 20, min_relevant: int = 3) -> List[Dict[str, Any]]:
        """Generate report on top companies by relevant job count"""
        from src.db.database import db
        from src.db.repositories import CompanyRepository, JobRepository

        async with db.session() as session:
            company_repo = CompanyRepository(session)
            companies = await company_repo.get_top_companies(limit=limit, min_relevant=min_relevant)
            
            job_repo = JobRepository(session)
            report = []
            
            for company in companies:
                jobs = await job_repo.get_company_jobs(company.id, relevant_only=True)
                
                # Quick stats
                tech_stack = []
                positions = []
                for job in jobs:
                    if job.extracted_tech:
                        tech_stack.extend(job.extracted_tech)
                    if job.title:
                        positions.append(job.title)
                
                from collections import Counter
                report.append({
                    "company": company.name,
                    "relevant_jobs": len(jobs),
                    "total_jobs": company.total_jobs_posted,
                    "top_tech": dict(Counter(tech_stack).most_common(10)),
                    "top_positions": dict(Counter(positions).most_common(5)),
                    "industry": company.industry,
                    "size": company.size,
                    "location": company.location,
                    "glassdoor_rating": company.glassdoor_rating,
                })
            
            return report

    async def find_companies_by_tech(self, technologies: List[str], min_jobs: int = 2) -> List[Dict]:
        """Find companies hiring for specific technologies"""
        from src.db.database import db
        from src.db.repositories import CompanyRepository, JobRepository
        
        async with db.session() as session:
            company_repo = CompanyRepository(session)
            job_repo = JobRepository(session)
            
            # Get all companies with relevant jobs
            companies = await company_repo.get_top_companies(limit=100, min_relevant=1)
            
            results = []
            for company in companies:
                jobs = await job_repo.get_company_jobs(company.id, relevant_only=True)
                
                # Check tech match
                company_tech = set()
                for job in jobs:
                    if job.extracted_tech:
                        company_tech.update(job.extracted_tech)
                
                matching_tech = [t for t in technologies if any(t.lower() in ct.lower() for ct in company_tech)]
                
                if len(matching_tech) > 0:
                    results.append({
                        "company": company.name,
                        "matching_technologies": matching_tech,
                        "all_technologies": list(company_tech),
                        "relevant_jobs": len(jobs),
                        "match_score": len(matching_tech) / len(technologies),
                    })
            
            # Sort by match score and relevant jobs
            results.sort(key=lambda x: (x["match_score"], x["relevant_jobs"]), reverse=True)
            return results

    async def get_interview_prep(self, company_name: str) -> Dict[str, Any]:
        """Get interview preparation materials for a company"""
        from src.db.database import db
        from src.db.repositories import CompanyRepository, JobRepository, CompanyIntelligenceRepository
        
        async with db.session() as session:
            company_repo = CompanyRepository(session)
            companies = await company_repo.search(company_name)
            
            if not companies:
                return {"error": "Company not found"}
            
            company = companies[0]
            job_repo = JobRepository(session)
            jobs = await job_repo.get_company_jobs(company.id, relevant_only=True)
            
            intel_repo = CompanyIntelligenceRepository(session)
            intelligence = await intel_repo.get_or_create(company.id)
            
            # Compile interview prep
            all_requirements = []
            all_questions = []
            interview_processes = []
            
            for job in jobs:
                for analysis in job.analyses:
                    if analysis.key_requirements:
                        all_requirements.extend(analysis.key_requirements)
                    if analysis.questions_to_ask:
                        all_questions.extend(analysis.questions_to_ask)
            
            from collections import Counter
            return {
                "company": company.name,
                "common_requirements": dict(Counter(all_requirements).most_common(15)),
                "strategic_questions": list(set(all_questions))[:10],
                "interview_process": intelligence.interview_process or {},
                "common_topics": intelligence.common_interview_topics or [],
                "difficulty": intelligence.interview_intelligence.get("difficulty", "unknown") if intelligence.interview_intelligence else "unknown",
                "take_home_likelihood": intelligence.take_home_frequency or 0,
                "tech_stack_focus": dict(Counter(
                    t for job in jobs for t in (job.extracted_tech or [])
                ).most_common(10)),
            }

    async def refresh_company_intelligence_by_name(self, name: str) -> Dict[str, Any]:
        """Refresh intelligence for a company by name"""
        from src.db.database import db
        from src.db.repositories import CompanyRepository, JobRepository
        
        async with db.session() as session:
            company_repo = CompanyRepository(session)
            companies = await company_repo.search(name)
            
            if not companies:
                return {"error": "Company not found"}
            
            company = companies[0]
            return await self.refresh_company_intelligence(company.id)