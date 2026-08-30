from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, 
    ForeignKey, Table, Index, Enum as SQLEnum
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from datetime import datetime
import enum


Base = declarative_base()


class JobRelevance(str, enum.Enum):
    HIGHLY_RELEVANT = "highly_relevant"
    RELEVANT = "relevant"
    POTENTIALLY_RELEVANT = "potentially_relevant"
    NOT_RELEVANT = "not_relevant"
    REJECTED = "rejected"


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255), unique=True, nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="channel")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, index=True)
    normalized_name = Column(String(500), nullable=False, unique=True, index=True)
    
    # Company intelligence
    industry = Column(String(255), nullable=True)
    size = Column(String(100), nullable=True)  # startup, small, medium, large, enterprise
    location = Column(String(500), nullable=True)
    website = Column(String(500), nullable=True)
    linkedin = Column(String(500), nullable=True)
    glassdoor_rating = Column(Float, nullable=True)
    glassdoor_reviews_count = Column(Integer, nullable=True)
    
    # Aggregated intelligence
    common_problems = Column(JSONB, nullable=True)  # List of {problem, frequency, sources}
    common_positions = Column(JSONB, nullable=True)  # List of {position, frequency, requirements}
    tech_stack = Column(JSONB, nullable=True)  # List of technologies mentioned
    hiring_patterns = Column(JSONB, nullable=True)  # Seasonal, remote policy, etc.
    culture_signals = Column(JSONB, nullable=True)  # Values, benefits, red flags
    
    # Metadata
    total_jobs_posted = Column(Integer, default=0)
    relevant_jobs_count = Column(Integer, default=0)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    jobs = relationship("Job", back_populates="company")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id = Column(Integer, nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    
    # Job content
    raw_text = Column(Text, nullable=False)
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    benefits = Column(Text, nullable=True)
    salary_range = Column(String(200), nullable=True)
    location = Column(String(500), nullable=True)
    remote_policy = Column(String(100), nullable=True)  # remote, hybrid, onsite
    job_type = Column(String(100), nullable=True)  # full-time, part-time, contract, internship
    experience_level = Column(String(100), nullable=True)  # junior, mid, senior, lead
    
    # Classification
    relevance_score = Column(Float, default=0.0)
    relevance_level = Column(SQLEnum(JobRelevance), default=JobRelevance.REJECTED)
    match_reasons = Column(JSONB, nullable=True)  # Why it matches/doesn't match
    extracted_skills = Column(ARRAY(String), nullable=True)
    extracted_tech = Column(ARRAY(String), nullable=True)
    
    # Metadata
    posted_at = Column(DateTime, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    channel = relationship("Channel")
    company = relationship("Company", back_populates="jobs")
    analyses = relationship("JobAnalysis", back_populates="job")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    text = Column(Text, nullable=True)
    date = Column(DateTime, nullable=False, index=True)
    sender_id = Column(Integer, nullable=True)
    is_job_post = Column(Boolean, default=False, index=True)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    channel = relationship("Channel", back_populates="messages")


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    
    # LLM Analysis
    summary = Column(Text, nullable=True)
    key_requirements = Column(ARRAY(String), nullable=True)
    nice_to_have = Column(ARRAY(String), nullable=True)
    red_flags = Column(ARRAY(String), nullable=True)
    culture_fit_score = Column(Float, nullable=True)
    growth_potential = Column(String(50), nullable=True)  # high, medium, low
    interview_difficulty = Column(String(50), nullable=True)  # easy, medium, hard
    estimated_salary_min = Column(Integer, nullable=True)
    estimated_salary_max = Column(Integer, nullable=True)
    
    # Application strategy
    application_tips = Column(Text, nullable=True)
    cover_letter_points = Column(ARRAY(String), nullable=True)
    questions_to_ask = Column(ARRAY(String), nullable=True)
    
    model_used = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="analyses")


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Professional info
    current_role = Column(String(200), nullable=True)
    years_experience = Column(Integer, nullable=True)
    skills = Column(ARRAY(String), nullable=True)
    tech_stack = Column(ARRAY(String), nullable=True)
    preferred_roles = Column(ARRAY(String), nullable=True)
    preferred_industries = Column(ARRAY(String), nullable=True)
    excluded_keywords = Column(ARRAY(String), nullable=True)
    
    # Preferences
    min_salary = Column(Integer, nullable=True)
    max_salary = Column(Integer, nullable=True)
    remote_preference = Column(String(50), nullable=True)  # remote, hybrid, onsite, any
    location_preferences = Column(ARRAY(String), nullable=True)
    visa_sponsorship_needed = Column(Boolean, default=False)
    
    # Company preferences
    company_size_preference = Column(ARRAY(String), nullable=True)  # startup, small, medium, large
    culture_values = Column(ARRAY(String), nullable=True)
    deal_breakers = Column(ARRAY(String), nullable=True)
    
    profile_text = Column(Text, nullable=True)  # Full profile for LLM context
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyIntelligence(Base):
    __tablename__ = "company_intelligence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, unique=True)
    
    # Aggregated from all job postings
    all_problems = Column(JSONB, nullable=True)  # Problem -> {count, examples, severity}
    all_positions = Column(JSONB, nullable=True)  # Position -> {count, requirements, frequency}
    tech_stack_evolution = Column(JSONB, nullable=True)  # Tech -> {first_seen, last_seen, frequency}
    hiring_timeline = Column(JSONB, nullable=True)  # Month -> {positions, count}
    
    # Derived insights
    problem_clusters = Column(JSONB, nullable=True)  # Grouped problems by domain
    team_structure_hints = Column(JSONB, nullable=True)  # Inferred from job titles
    tech_debt_signals = Column(JSONB, nullable=True)  # Legacy mentions, migrations, refactors
    growth_signals = Column(JSONB, nullable=True)  # Scaling, new products, funding
    
    # Interview intelligence
    interview_process = Column(JSONB, nullable=True)  # Stages, duration, focus areas
    common_interview_topics = Column(ARRAY(String), nullable=True)
    take_home_frequency = Column(Float, nullable=True)
    
    # Competitive intelligence
    competitors_mentioned = Column(ARRAY(String), nullable=True)
    market_position = Column(String(100), nullable=True)
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    confidence_score = Column(Float, default=0.0)  # Based on data volume
    
    company = relationship("Company")


# Indexes for performance
Index("ix_jobs_company_relevance", Job.company_id, Job.relevance_level)
Index("ix_jobs_posted_relevance", Job.posted_at, Job.relevance_level)
Index("ix_messages_channel_date", Message.channel_id, Message.date)