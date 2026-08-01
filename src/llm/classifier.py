from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from enum import Enum
import json
import logging

from src.db.models import UserProfile
from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


class JobRelevance(str, Enum):
    HIGHLY_RELEVANT = "highly_relevant"
    RELEVANT = "relevant"
    POTENTIALLY_RELEVANT = "potentially_relevant"
    NOT_RELEVANT = "not_relevant"
    REJECTED = "rejected"


class JobClassification(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="Relevance score 0-1")
    level: JobRelevance
    reasons: Dict[str, str] = Field(default_factory=dict)
    skills: List[str] = Field(default_factory=list)
    tech_stack: List[str] = Field(default_factory=list)
    role_level: Optional[str] = None
    remote_friendly: bool = True
    salary_mentioned: bool = False
    visa_sponsorship_mentioned: bool = False


CLASSIFICATION_PROMPT = """You are an expert technical recruiter evaluating job postings for a candidate.

CANDIDATE PROFILE:
{profile}

JOB POSTING:
Company: {company}
Text: {job_text}

Evaluate this job posting and return a JSON object with:
{{
    "score": 0.0-1.0,
    "level": "highly_relevant|relevant|potentially_relevant|not_relevant|rejected",
    "reasons": {{
        "match": "Why this matches (or doesn't match) the candidate",
        "skills_match": "Skill overlap analysis",
        "level_match": "Seniority level match",
        "location_match": "Remote/location compatibility",
        "concerns": "Any red flags or concerns"
    }},
    "skills": ["extracted", "skills", "from", "posting"],
    "tech_stack": ["technologies", "mentioned"],
    "role_level": "junior|mid|senior|lead|principal",
    "remote_friendly": true/false,
    "salary_mentioned": true/false,
    "visa_sponsorship_mentioned": true/false
}}

SCORING GUIDELINES:
- 0.9-1.0: Perfect match - skills, level, location, compensation all align
- 0.7-0.89: Strong match - minor gaps in nice-to-haves
- 0.5-0.69: Partial match - some gaps in required skills or level
- 0.3-0.49: Weak match - significant gaps
- 0.0-0.29: Poor match - major mismatches or red flags

RED FLAGS (auto-reject or heavily penalize):
- Visa sponsorship explicitly not offered when candidate needs it
- On-site only when candidate needs remote
- Skills completely mismatched
- Unrealistic requirements (10 years exp in 5 year old tech)
- Toxic culture signals (rockstar, ninja, work hard play hard, etc.)"""


class JobClassifier:
    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    def _build_profile_text(self, profile: UserProfile) -> str:
        parts = []
        if profile.current_role:
            parts.append(f"Current Role: {profile.current_role}")
        if profile.years_experience:
            parts.append(f"Years Experience: {profile.years_experience}")
        if profile.skills:
            parts.append(f"Core Skills: {', '.join(profile.skills)}")
        if profile.tech_stack:
            parts.append(f"Tech Stack: {', '.join(profile.tech_stack)}")
        if profile.preferred_roles:
            parts.append(f"Target Roles: {', '.join(profile.preferred_roles)}")
        if profile.preferred_industries:
            parts.append(f"Preferred Industries: {', '.join(profile.preferred_industries)}")
        if profile.min_salary:
            parts.append(f"Min Salary: {profile.min_salary}")
        if profile.remote_preference:
            parts.append(f"Remote Preference: {profile.remote_preference}")
        if profile.location_preferences:
            parts.append(f"Preferred Locations: {', '.join(profile.location_preferences)}")
        if profile.visa_sponsorship_needed:
            parts.append("VISA SPONSORSHIP REQUIRED")
        if profile.excluded_keywords:
            parts.append(f"Exclude: {', '.join(profile.excluded_keywords)}")
        if profile.deal_breakers:
            parts.append(f"Deal Breakers: {', '.join(profile.deal_breakers)}")
        if profile.profile_text:
            parts.append(f"Additional Context: {profile.profile_text}")
        return "\n".join(parts) if parts else "No profile configured"

    async def classify_job(self, job_text: str, company_name: str, 
                           profile: UserProfile) -> JobClassification:
        profile_text = self._build_profile_text(profile)
        
        prompt = CLASSIFICATION_PROMPT.format(
            profile=profile_text,
            company=company_name,
            job_text=job_text[:8000]
        )
        
        try:
            response = await self.llm.complete(
                prompt,
                system_prompt="You are an expert technical recruiter. Return only valid JSON.",
                temperature=0.1,
                max_tokens=1000
            )
            
            data = json.loads(response)
            return JobClassification(**data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return self._fallback_classification(job_text)
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return self._fallback_classification(job_text)

    def _fallback_classification(self, job_text: str) -> JobClassification:
        """Basic keyword-based fallback"""
        text_lower = job_text.lower()
        
        # Basic scoring
        score = 0.3
        reasons = {"match": "Fallback classification - LLM unavailable"}
        skills = []
        tech_stack = []
        
        # Check for common tech keywords
        tech_keywords = {
            "python": "Python", "java": "Java", "javascript": "JavaScript",
            "typescript": "TypeScript", "go": "Go", "golang": "Go",
            "rust": "Rust", "react": "React", "vue": "Vue", "angular": "Angular",
            "node": "Node.js", "django": "Django", "fastapi": "FastAPI",
            "spring": "Spring", "aws": "AWS", "gcp": "GCP", "azure": "Azure",
            "docker": "Docker", "kubernetes": "Kubernetes", "sql": "SQL",
            "postgres": "PostgreSQL", "mongodb": "MongoDB", "redis": "Redis",
        }
        
        for kw, name in tech_keywords.items():
            if kw in text_lower:
                tech_stack.append(name)
                skills.append(name)
                score += 0.05
        
        # Seniority
        role_level = None
        if any(w in text_lower for w in ["senior", "sr.", "lead", "principal", "staff"]):
            role_level = "senior"
            score += 0.1
        elif any(w in text_lower for w in ["junior", "jr.", "entry", "graduate"]):
            role_level = "junior"
        
        # Remote
        remote_friendly = any(w in text_lower for w in ["remote", "remoto", "distributed"])
        
        level = JobRelevance.POTENTIALLY_RELEVANT
        if score >= 0.7:
            level = JobRelevance.RELEVANT
        elif score >= 0.5:
            level = JobRelevance.POTENTIALLY_RELEVANT
        elif score < 0.3:
            level = JobRelevance.REJECTED
        
        return JobClassification(
            score=min(score, 1.0),
            level=level,
            reasons=reasons,
            skills=list(set(skills)),
            tech_stack=list(set(tech_stack)),
            role_level=role_level,
            remote_friendly=remote_friendly,
        )

    async def batch_classify(self, jobs: List[tuple], profile: UserProfile) -> List[JobClassification]:
        """Classify multiple jobs efficiently"""
        results = []
        for job_text, company_name in jobs:
            result = await self.classify_job(job_text, company_name, profile)
            results.append(result)
        return results