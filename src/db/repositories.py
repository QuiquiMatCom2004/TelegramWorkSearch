from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json

from src.db.models import (
    Channel, Company, Job, Message, JobAnalysis, 
    UserProfile, CompanyIntelligence, JobRelevance
)
from src.db.database import db


class ChannelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, telegram_id: int, username: str = None, 
                           title: str = "", description: str = None) -> Channel:
        stmt = select(Channel).where(Channel.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        channel = result.scalar_one_or_none()
        
        if not channel:
            channel = Channel(
                telegram_id=telegram_id,
                username=username,
                title=title,
                description=description,
            )
            self.session.add(channel)
            await self.session.flush()
        else:
            channel.username = username
            channel.title = title
            channel.description = description
            channel.updated_at = datetime.utcnow()
        
        return channel

    async def get_active_channels(self) -> List[Channel]:
        stmt = select(Channel).where(Channel.is_active == True)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class CompanyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _normalize_name(self, name: str) -> str:
        return name.strip().lower().replace(" ", "_").replace(".", "").replace(",", "")

    async def get_or_create(self, name: str, **kwargs) -> Company:
        normalized = self._normalize_name(name)
        stmt = select(Company).where(Company.normalized_name == normalized)
        result = await self.session.execute(stmt)
        company = result.scalar_one_or_none()
        
        if not company:
            company = Company(
                name=name.strip(),
                normalized_name=normalized,
                **kwargs
            )
            self.session.add(company)
            await self.session.flush()
        else:
            for key, value in kwargs.items():
                if value and not getattr(company, key):
                    setattr(company, key, value)
            company.updated_at = datetime.utcnow()
        
        return company

    async def get_by_id(self, company_id: int) -> Optional[Company]:
        stmt = select(Company).where(Company.id == company_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_top_companies(self, limit: int = 20, min_relevant: int = 3) -> List[Company]:
        stmt = (
            select(Company)
            .where(Company.relevant_jobs_count >= min_relevant)
            .order_by(desc(Company.relevant_jobs_count))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def search(self, query: str) -> List[Company]:
        stmt = select(Company).where(
            or_(
                Company.name.ilike(f"%{query}%"),
                Company.normalized_name.ilike(f"%{query}%")
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Job:
        job = Job(**kwargs)
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_message_id(self, message_id: int, channel_id: int) -> Optional[Job]:
        stmt = select(Job).where(
            and_(Job.telegram_message_id == message_id, Job.channel_id == channel_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_relevant_jobs(self, limit: int = 50, min_score: float = 0.7) -> List[Job]:
        stmt = (
            select(Job)
            .options(selectinload(Job.company), selectinload(Job.analyses))
            .where(Job.relevance_score >= min_score)
            .order_by(desc(Job.relevance_score), desc(Job.posted_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_company_jobs(self, company_id: int, relevant_only: bool = False) -> List[Job]:
        stmt = select(Job).where(Job.company_id == company_id)
        if relevant_only:
            stmt = stmt.where(Job.relevance_score >= 0.7)
        stmt = stmt.order_by(desc(Job.posted_at))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_relevance(self, job_id: int, score: float, level: JobRelevance, 
                               reasons: Dict, skills: List[str], tech: List[str]):
        stmt = select(Job).where(Job.id == job_id)
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if job:
            job.relevance_score = score
            job.relevance_level = level
            job.match_reasons = reasons
            job.extracted_skills = skills
            job.extracted_tech = tech
            job.processed_at = datetime.utcnow()

    async def get_stats(self) -> Dict[str, Any]:
        total = await self.session.execute(select(func.count(Job.id)))
        relevant = await self.session.execute(
            select(func.count(Job.id)).where(Job.relevance_score >= 0.7)
        )
        by_level = await self.session.execute(
            select(Job.relevance_level, func.count(Job.id))
            .group_by(Job.relevance_level)
        )
        return {
            "total": total.scalar(),
            "relevant": relevant.scalar(),
            "by_level": dict(by_level.all())
        }


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Message:
        msg = Message(**kwargs)
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def exists(self, telegram_id: int, channel_id: int) -> bool:
        stmt = select(Message.id).where(
            and_(Message.telegram_id == telegram_id, Message.channel_id == channel_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_unprocessed_jobs(self, limit: int = 100) -> List[Message]:
        stmt = (
            select(Message)
            .where(and_(Message.is_job_post == True, Message.processed == False))
            .order_by(Message.date)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def mark_processed(self, message_id: int):
        stmt = select(Message).where(Message.id == message_id)
        result = await self.session.execute(stmt)
        msg = result.scalar_one_or_none()
        if msg:
            msg.processed = True


class JobAnalysisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, job_id: int, **kwargs) -> JobAnalysis:
        analysis = JobAnalysis(job_id=job_id, **kwargs)
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def get_latest_for_job(self, job_id: int) -> Optional[JobAnalysis]:
        stmt = (
            select(JobAnalysis)
            .where(JobAnalysis.job_id == job_id)
            .order_by(desc(JobAnalysis.created_at))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class UserProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self) -> UserProfile:
        stmt = select(UserProfile)
        result = await self.session.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if not profile:
            profile = UserProfile()
            self.session.add(profile)
            await self.session.flush()
        
        return profile

    async def update_profile(self, **kwargs) -> UserProfile:
        profile = await self.get_or_create()
        for key, value in kwargs.items():
            if hasattr(profile, key) and value is not None:
                setattr(profile, key, value)
        profile.updated_at = datetime.utcnow()
        return profile


class CompanyIntelligenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, company_id: int) -> CompanyIntelligence:
        stmt = select(CompanyIntelligence).where(CompanyIntelligence.company_id == company_id)
        result = await self.session.execute(stmt)
        intel = result.scalar_one_or_none()
        
        if not intel:
            intel = CompanyIntelligence(company_id=company_id)
            self.session.add(intel)
            await self.session.flush()
        
        return intel

    async def update_intelligence(self, company_id: int, **kwargs):
        intel = await self.get_or_create(company_id)
        for key, value in kwargs.items():
            if hasattr(intel, key) and value is not None:
                setattr(intel, key, value)
        intel.last_updated = datetime.utcnow()
        return intel