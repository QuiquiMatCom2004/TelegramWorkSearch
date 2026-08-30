from telethon import TelegramClient, events
from telethon.tl.types import Channel as TelethonChannel, MessageMediaPhoto, MessageMediaDocument
from telethon.errors import FloodWaitError, ChannelPrivateError
from datetime import datetime, timedelta
from typing import List, Optional, Callable, Awaitable
import asyncio
import logging
import re

from config.settings import settings
from src.db.database import db
from src.db.repositories import (
    ChannelRepository, CompanyRepository, JobRepository,
    MessageRepository, UserProfileRepository, JobAnalysisRepository
)
from src.db.models import Channel, Company, Message, Job, JobRelevance
from src.llm.classifier import JobClassifier
from src.llm.company_intelligence import CompanyIntelligenceAnalyzer

logger = logging.getLogger(__name__)


class JobChannelMonitor:
    def __init__(self):
        self.client = TelegramClient(
            "job_search_session",
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )
        self.classifier = JobClassifier()
        self.intelligence = CompanyIntelligenceAnalyzer()
        self.running = False

    async def start(self):
        await self.client.start(phone=settings.telegram_phone)
        await db.initialize()
        await db.create_tables()
        self.running = True
        logger.info("Telegram client started")

    async def stop(self):
        self.running = False
        await self.client.disconnect()
        await db.close()
        logger.info("Telegram client stopped")

    async def join_channels(self, channel_usernames: List[str]) -> List[Channel]:
        """Join channels and store in database"""
        channels = []
        for username in channel_usernames:
            try:
                entity = await self.client.get_entity(username)
                if isinstance(entity, TelethonChannel):
                    async with db.session() as session:
                        repo = ChannelRepository(session)
                        channel = await repo.get_or_create(
                            telegram_id=entity.id,
                            username=entity.username,
                            title=entity.title,
                            description=getattr(entity, 'about', None)
                        )
                        channels.append(channel)
                        logger.info(f"Joined channel: {entity.title} (@{entity.username})")
            except ChannelPrivateError:
                logger.warning(f"Cannot access private channel: {username}")
            except FloodWaitError as e:
                logger.warning(f"Flood wait: {e.seconds}s for {username}")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Error joining {username}: {e}")
        return channels

    async def fetch_recent_messages(self, channel: Channel, limit: int = 100, 
                                     days_back: int = 7) -> List[Message]:
        """Fetch recent messages from a channel"""
        messages = []
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        async with db.session() as session:
            msg_repo = MessageRepository(session)
            
            async for msg in self.client.iter_messages(
                channel.telegram_id, 
                limit=limit,
                offset_date=cutoff_date
            ):
                if msg.id and not await msg_repo.exists(msg.id, channel.id):
                    messages.append(msg)
        
        return messages

    async def process_channel(self, channel: Channel, limit: int = 100, 
                              days_back: int = 7) -> int:
        """Process messages from a single channel"""
        messages = await self.fetch_recent_messages(channel, limit, days_back)
        processed = 0
        
        for msg in messages:
            try:
                await self.process_message(msg, channel)
                processed += 1
            except Exception as e:
                logger.error(f"Error processing message {msg.id}: {e}")
        
        return processed

    async def process_message(self, telegram_msg: Message, channel: Channel):
        """Process a single Telegram message"""
        async with db.session() as session:
            msg_repo = MessageRepository(session)
            job_repo = JobRepository(session)
            company_repo = CompanyRepository(session)
            
            # Check if already processed
            if await msg_repo.exists(telegram_msg.id, channel.id):
                return

            # Store message
            msg_text = telegram_msg.text or telegram_msg.message or ""
            message = await msg_repo.create(
                telegram_id=telegram_msg.id,
                channel_id=channel.id,
                text=msg_text,
                date=telegram_msg.date.replace(tzinfo=None),
                sender_id=telegram_msg.sender_id,
            )

            # Check if it's a job post
            is_job = self._is_job_post(msg_text)
            message.is_job_post = is_job
            
            if not is_job:
                return

            # Extract company name
            company_name = self._extract_company_name(msg_text, telegram_msg)
            if not company_name:
                return

            # Get or create company
            company = await company_repo.get_or_create(company_name)

            # Check if job already exists
            existing_job = await job_repo.get_by_message_id(telegram_msg.id, channel.id)
            if existing_job:
                return

            # Classify job relevance
            async with db.session() as profile_session:
                profile_repo = UserProfileRepository(profile_session)
                profile = await profile_repo.get_or_create()
            
            classification = await self.classifier.classify_job(msg_text, company_name, profile)
            
            # Create job record
            job = await job_repo.create(
                telegram_message_id=telegram_msg.id,
                channel_id=channel.id,
                company_id=company.id,
                raw_text=msg_text,
                title=self._extract_title(msg_text),
                description=msg_text[:5000],
                posted_at=telegram_msg.date.replace(tzinfo=None),
                relevance_score=classification.score,
                relevance_level=classification.level,
                match_reasons=classification.reasons,
                extracted_skills=classification.skills,
                extracted_tech=classification.tech_stack,
            )

            # Update company stats
            await self._update_company_stats(session, company, classification)
            
            # Analyze job in detail
            if classification.level in [JobRelevance.HIGHLY_RELEVANT, JobRelevance.RELEVANT]:
                await self._analyze_job(job, msg_text, company, profile)

    def _is_job_post(self, text: str) -> bool:
        """Heuristic to detect job postings"""
        job_keywords = [
            r"\b(?:buscamos|busco|contratamos|contrato|hiring|hiring|vacante|vacancy)\b",
            r"\b(?:developer|desarrollador|engineer|ingeniero|programador)\b",
            r"\b(?:junior|senior|lead|principal|staff)\b.*\b(?:dev|developer|engineer)\b",
            r"\b(?:react|python|java|go|golang|node|javascript|typescript)\b.*\b(?:developer|engineer)\b",
            r"\b(?:remoto|remote|hybrid|híbrido)\b.*\b(?:work|trabajo|job|empleo)\b",
            r"\b(?:salary|salario|sueldo|compensation|beneficios)\b",
            r"\b(?:apply|aplica|aplicar|cv|resume|curriculum)\b",
        ]
        
        text_lower = text.lower()
        matches = sum(1 for pattern in job_keywords if re.search(pattern, text_lower, re.IGNORECASE))
        return matches >= 2

    def _extract_company_name(self, text: str, msg: Message) -> str:
        """Extract company name from message"""
        # Check forwarded from
        if msg.forward and msg.forward.from_id:
            try:
                # This would need entity resolution
                pass
            except:
                pass
        
        # Common patterns
        patterns = [
            r"(?:en|at|@)\s+([A-Z][a-zA-Z0-9\s&.]+?)(?:\s+(?:busca|busca|hiring|contrata|buscamos))",
            r"^([A-Z][a-zA-Z0-9\s&.]{2,50}?)\s+(?:busca|busca|hiring|contrata)",
            r"🏢\s*([A-Z][a-zA-Z0-9\s&.]{2,50})",
            r"Company[:\s]+([A-Z][a-zA-Z0-9\s&.]{2,50})",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > 2 and len(name) < 100:
                    return name
        
        # Fallback: check channel username/title
        return ""

    def _extract_title(self, text: str) -> str:
        """Extract job title from text"""
        lines = text.split('\n')
        for line in lines[:5]:
            line = line.strip()
            if any(kw in line.lower() for kw in ['busca', 'hiring', 'vacante', 'se busca', 'developer', 'engineer']):
                if len(line) < 150:
                    return line
        return lines[0][:150] if lines else ""

    async def _update_company_stats(self, session, company: Company, classification):
        company.total_jobs_posted += 1
        if classification.level in [JobRelevance.HIGHLY_RELEVANT, JobRelevance.RELEVANT]:
            company.relevant_jobs_count += 1
        company.last_job_posted = datetime.utcnow()

    async def _analyze_job(self, job: Job, text: str, company: Company, profile):
        """Deep analysis of relevant job"""
        analysis = await self.intelligence.analyze_job_posting(text, company.name, profile)
        
        async with db.session() as session:
            analysis_repo = JobAnalysisRepository(session)
            await analysis_repo.create(
                job_id=job.id,
                **analysis
            )

    async def run_monitoring(self, channel_usernames: List[str], interval: int = 300):
        """Run continuous monitoring"""
        await self.join_channels(channel_usernames)
        
        while self.running:
            try:
                async with db.session() as session:
                    channel_repo = ChannelRepository(session)
                    channels = await channel_repo.get_active_channels()
                
                for channel in channels:
                    if not self.running:
                        break
                    try:
                        count = await self.process_channel(channel)
                        logger.info(f"Processed {count} new messages from {channel.title}")
                    except Exception as e:
                        logger.error(f"Error processing channel {channel.title}: {e}")
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)

    async def get_company_intelligence(self, company_name: str) -> dict:
        """Get aggregated intelligence for a company"""
        async with db.session() as session:
            company_repo = CompanyRepository(session)
            companies = await company_repo.search(company_name)
            
            if not companies:
                return {"error": "Company not found"}
            
            company = companies[0]
            jobs = await JobRepository(session).get_company_jobs(company.id)
            
            return await self.intelligence.aggregate_company_intelligence(company, jobs)


async def main():
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.telegram.monitor <channel1> [channel2] ...")
        return
    
    monitor = JobChannelMonitor()
    await monitor.start()
    
    try:
        await monitor.run_monitoring(sys.argv[1:])
    except KeyboardInterrupt:
        await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())