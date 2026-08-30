from openai import AsyncOpenAI
from typing import Optional, List, Dict, Any
import logging
import asyncio
import re

from config.settings import settings

logger = logging.getLogger(__name__)


def strip_json_fence(text: str) -> str:
    """Strip a ```json ... ``` (or ``` ... ```) fence some models wrap JSON output in."""
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text.strip(), re.DOTALL)
    return match.group(1) if match else text


class LLMClient:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.client = AsyncOpenAI(
            api_key=api_key or settings.openrouter_api_key,
            base_url=base_url or settings.openrouter_base_url,
        )
        self.model = model or settings.llm_model
        self.default_temperature = settings.llm_temperature

    async def complete(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = None,
        max_tokens: int = 2000,
        response_format: Dict = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        try:
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM completion error: {e}")
            raise

    async def complete_with_retry(
        self,
        prompt: str,
        system_prompt: str = None,
        max_retries: int = 3,
        **kwargs
    ) -> str:
        for attempt in range(max_retries):
            try:
                return await self.complete(prompt, system_prompt, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

    async def analyze_company_intelligence(
        self,
        company_name: str,
        job_postings: List[str],
        profile_text: str = ""
    ) -> Dict[str, Any]:
        """Deep analysis of company from all job postings"""
        prompt = f"""Analyze this company based on their job postings.

Company: {company_name}
Candidate Profile: {profile_text}

JOB POSTINGS ({len(job_postings)} total):
{chr(10).join(f"--- Posting {i+1} ---\n{post[:3000]}" for i, post in enumerate(job_postings[:20]))}

Return JSON with:
{{
    "common_problems": [
        {{"problem": "string", "frequency": int, "severity": "high|medium|low", "example_snippets": ["..."]}}
    ],
    "common_positions": [
        {{"position": "string", "frequency": int, "typical_requirements": ["..."], "seniority_distribution": {{}}}}
    ],
    "tech_stack": [
        {{"technology": "string", "frequency": int, "context": "required|preferred|nice-to-have", "trend": "increasing|stable|decreasing"}}
    ],
    "hiring_patterns": {{
        "remote_policy": "remote|hybrid|onsite|varies",
        "visa_sponsorship": "yes|no|sometimes|unknown",
        "hiring_volume": "high|medium|low",
        "seasonal_patterns": "description"
    }},
    "culture_signals": {{
        "values_mentioned": ["..."],
        "benefits": ["..."],
        "red_flags": ["..."],
        "green_flags": ["..."]
    }},
    "problem_clusters": {{
        "domain": ["related problems"]
    }},
    "tech_debt_signals": [
        {{"signal": "string", "evidence": "string", "severity": "high|medium|low"}}
    ],
    "growth_signals": [
        {{"signal": "string", "evidence": "string"}}
    ],
    "interview_intelligence": {{
        "process_stages": ["..."],
        "common_topics": ["..."],
        "take_home_frequency": 0.0-1.0,
        "difficulty": "easy|medium|hard"
    }},
    "competitors_mentioned": ["..."],
    "market_position": "leader|challenger|niche|unknown",
    "confidence_score": 0.0-1.0
}}"""

        response = await self.complete(
            prompt,
            system_prompt="You are an expert competitive intelligence analyst. Return only valid JSON.",
            temperature=0.2,
            max_tokens=4000
        )
        import json
        return json.loads(strip_json_fence(response))

    async def analyze_job_for_application(
        self,
        job_text: str,
        company_name: str,
        company_intelligence: Dict,
        profile_text: str
    ) -> Dict[str, Any]:
        """Analyze a specific job for application strategy"""
        prompt = f"""Analyze this specific job posting for application strategy.

Company: {company_name}
Job Posting: {job_text[:5000]}

Company Intelligence Summary:
- Common problems: {company_intelligence.get('common_problems', [])[:5]}
- Tech stack: {company_intelligence.get('tech_stack', [])[:10]}
- Culture signals: {company_intelligence.get('culture_signals', {})}
- Interview process: {company_intelligence.get('interview_intelligence', {})}

Candidate Profile: {profile_text}

Return JSON with:
{{
    "summary": "2-3 sentence summary of the role",
    "key_requirements": ["must-have requirements"],
    "nice_to_have": ["nice-to-have requirements"],
    "red_flags": ["concerns about role/company"],
    "culture_fit_score": 0.0-1.0,
    "growth_potential": "high|medium|low",
    "interview_difficulty": "easy|medium|hard",
    "estimated_salary_min": int,
    "estimated_salary_max": int,
    "application_tips": "specific advice for this application",
    "cover_letter_points": ["key points to emphasize"],
    "questions_to_ask": ["strategic questions for interview"],
    "referral_strategy": "how to get referred if possible"
}}"""

        response = await self.complete(
            prompt,
            system_prompt="You are an expert career coach and technical recruiter. Return only valid JSON.",
            temperature=0.3,
            max_tokens=3000
        )
        import json
        return json.loads(strip_json_fence(response))