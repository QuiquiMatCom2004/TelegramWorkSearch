import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from typing import Optional, List
import asyncio
import json
import logging

from config.settings import settings
from src.db.database import db
from src.db.repositories import (
    ChannelRepository, CompanyRepository, JobRepository,
    UserProfileRepository, CompanyIntelligenceRepository
)
from src.db.models import JobRelevance, UserProfile
from src.telegram.monitor import JobChannelMonitor
from src.llm.classifier import JobClassifier
from src.llm.company_intelligence import CompanyIntelligenceService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Telegram Job Search Intelligence")
console = Console()

# Global instances
monitor = JobChannelMonitor()
classifier = JobClassifier()
intel_service = CompanyIntelligenceService()


@app.command()
def setup():
    """Initial setup - configure profile and channels"""
    console.print(Panel.fit("🔧 [bold]Telegram Job Search Setup[/bold]", border_style="blue"))
    
    asyncio.run(_setup_profile())
    asyncio.run(_setup_channels())


async def _setup_profile():
    console.print("\n[bold]📋 Candidate Profile Setup[/bold]")
    
    async with db.session() as session:
        repo = UserProfileRepository(session)
        profile = await repo.get_or_create()
        
        profile.current_role = Prompt.ask("Current role", default=profile.current_role or "")
        profile.years_experience = int(Prompt.ask("Years of experience", default=str(profile.years_experience or 0)))
        
        skills = Prompt.ask("Core skills (comma-separated)", default=", ".join(profile.skills or []))
        profile.skills = [s.strip() for s in skills.split(",") if s.strip()]
        
        tech = Prompt.ask("Tech stack (comma-separated)", default=", ".join(profile.tech_stack or []))
        profile.tech_stack = [t.strip() for t in tech.split(",") if t.strip()]
        
        roles = Prompt.ask("Target roles (comma-separated)", default=", ".join(profile.preferred_roles or []))
        profile.preferred_roles = [r.strip() for r in roles.split(",") if r.strip()]
        
        profile.min_salary = int(Prompt.ask("Minimum salary (annual)", default=str(profile.min_salary or 0))) or None
        profile.remote_preference = Prompt.ask(
            "Remote preference", 
            choices=["remote", "hybrid", "onsite", "any"],
            default=profile.remote_preference or "remote"
        )
        
        locations = Prompt.ask("Preferred locations (comma-separated)", default=", ".join(profile.location_preferences or []))
        profile.location_preferences = [l.strip() for l in locations.split(",") if l.strip()]
        
        profile.visa_sponsorship_needed = Confirm.ask("Need visa sponsorship?", default=profile.visa_sponsorship_needed or False)
        
        excluded = Prompt.ask("Excluded keywords (comma-separated)", default=", ".join(profile.excluded_keywords or []))
        profile.excluded_keywords = [e.strip() for e in excluded.split(",") if e.strip()]
        
        deal_breakers = Prompt.ask("Deal breakers (comma-separated)", default=", ".join(profile.deal_breakers or []))
        profile.deal_breakers = [d.strip() for d in deal_breakers.split(",") if d.strip()]
        
        profile.profile_text = Prompt.ask("Additional context for LLM (optional)", default=profile.profile_text or "")
        
        await repo.update_profile(**{
            "current_role": profile.current_role,
            "years_experience": profile.years_experience,
            "skills": profile.skills,
            "tech_stack": profile.tech_stack,
            "preferred_roles": profile.preferred_roles,
            "min_salary": profile.min_salary,
            "remote_preference": profile.remote_preference,
            "location_preferences": profile.location_preferences,
            "visa_sponsorship_needed": profile.visa_sponsorship_needed,
            "excluded_keywords": profile.excluded_keywords,
            "deal_breakers": profile.deal_breakers,
            "profile_text": profile.profile_text,
        })
        
        console.print("✅ Profile saved!")


async def _setup_channels():
    console.print("\n[bold]📺 Telegram Channels Setup[/bold]")
    
    console.print("Enter channel usernames (without @) or IDs, one per line.")
    console.print("Press Enter on empty line to finish.")
    
    channels = []
    while True:
        channel = Prompt.ask("Channel", default="")
        if not channel:
            break
        channels.append(channel)
    
    if channels:
        console.print(f"\nJoining {len(channels)} channels...")
        await monitor.start()
        try:
            joined = await monitor.join_channels(channels)
            console.print(f"✅ Joined {len(joined)} channels:")
            for ch in joined:
                console.print(f"  • {ch.title} (@{ch.username or ch.telegram_id})")
        finally:
            await monitor.stop()
    else:
        console.print("No channels added.")


@app.command()
def scan(
    channels: Optional[List[str]] = typer.Option(None, "--channel", "-c", help="Channels to scan"),
    days: int = typer.Option(7, "--days", "-d", help="Days back to scan"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max messages per channel"),
):
    """Scan channels for job postings"""
    console.print(Panel.fit("🔍 [bold]Scanning Channels[/bold]", border_style="green"))
    
    async def _scan():
        await monitor.start()
        try:
            if channels:
                await monitor.join_channels(channels)
            
            async with db.session() as session:
                channel_repo = ChannelRepository(session)
                chs = await channel_repo.get_active_channels()
            
            if not chs:
                console.print("❌ No active channels. Run 'setup' first.")
                return
            
            total_processed = 0
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                for channel in chs:
                    task = progress.add_task(f"Scanning {channel.title}...", total=None)
                    count = await monitor.process_channel(channel, limit=limit, days_back=days)
                    total_processed += count
                    progress.update(task, description=f"✅ {channel.title}: {count} new messages")
            
            console.print(f"\n✅ Scan complete! Processed {total_processed} new messages.")
            
            # Show stats
            async with db.session() as session:
                job_repo = JobRepository(session)
                stats = await job_repo.get_stats()
            
            table = Table(title="📊 Database Stats")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="magenta")
            for k, v in stats.items():
                if k != "by_level":
                    table.add_row(k.replace("_", " ").title(), str(v))
            console.print(table)
            
        finally:
            await monitor.stop()
    
    asyncio.run(_scan())


@app.command()
def monitor(
    interval: int = typer.Option(300, "--interval", "-i", help="Check interval in seconds"),
    channels: Optional[List[str]] = typer.Option(None, "--channel", "-c", help="Channels to monitor"),
):
    """Run continuous monitoring"""
    console.print(Panel.fit("🔄 [bold]Starting Continuous Monitor[/bold]", border_style="yellow"))
    console.print(f"Check interval: {interval}s")
    console.print("Press Ctrl+C to stop\n")
    
    async def _monitor():
        await monitor.start()
        try:
            if channels:
                await monitor.join_channels(channels)
            await monitor.run_monitoring(channels or [], interval)
        except KeyboardInterrupt:
            console.print("\n🛑 Stopping monitor...")
        finally:
            await monitor.stop()
    
    asyncio.run(_monitor())


@app.command()
def jobs(
    min_score: float = typer.Option(0.7, "--min-score", help="Minimum relevance score"),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of jobs to show"),
    company: Optional[str] = typer.Option(None, "--company", help="Filter by company"),
):
    """List relevant job postings"""
    console.print(Panel.fit("💼 [bold]Relevant Jobs[/bold]", border_style="blue"))
    
    async def _jobs():
        async with db.session() as session:
            job_repo = JobRepository(session)
            jobs = await job_repo.get_relevant_jobs(limit=limit, min_score=min_score)
            
            if company:
                jobs = [j for j in jobs if j.company and company.lower() in j.company.name.lower()]
            
            if not jobs:
                console.print("No jobs found matching criteria.")
                return
            
            table = Table()
            table.add_column("Score", style="green", width=6)
            table.add_column("Company", style="cyan", width=25)
            table.add_column("Title", style="white", width=40)
            table.add_column("Location", style="yellow", width=20)
            table.add_column("Remote", style="magenta", width=8)
            table.add_column("Posted", style="dim", width=12)
            
            for job in jobs:
                score_color = "green" if job.relevance_score >= 0.8 else "yellow" if job.relevance_score >= 0.6 else "red"
                table.add_row(
                    f"[{score_color}]{job.relevance_score:.2f}[/{score_color}]",
                    job.company.name if job.company else "Unknown",
                    (job.title or "N/A")[:38],
                    (job.location or "N/A")[:18],
                    job.remote_policy or "N/A",
                    job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "N/A",
                )
            
            console.print(table)
    
    asyncio.run(_jobs())


@app.command()
def company(
    name: str = typer.Argument(..., help="Company name to analyze"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Refresh intelligence from LLM"),
):
    """Analyze a specific company"""
    console.print(Panel.fit(f"🏢 [bold]Company Analysis: {name}[/bold]", border_style="blue"))
    
    async def _company():
        if refresh:
            with console.status("Refreshing intelligence..."):
                result = await intel_service.refresh_company_intelligence_by_name(name)
        else:
            with console.status("Loading intelligence..."):
                result = await intel_service.get_interview_prep(name)
        
        if "error" in result:
            console.print(f"❌ {result['error']}")
            return
        
        # Company overview
        console.print(f"\n[bold]Company:[/bold] {result.get('company', name)}")
        console.print(f"[bold]Relevant Jobs:[/bold] {result.get('relevant_jobs', 0)}")
        
        if 'top_tech' in result:
            console.print("\n[bold]Top Technologies:[/bold]")
            for tech, count in list(result['top_tech'].items())[:10]:
                console.print(f"  • {tech}: {count}")
        
        if 'common_requirements' in result:
            console.print("\n[bold]Common Requirements:[/bold]")
            for req, count in list(result['common_requirements'].items())[:10]:
                console.print(f"  • {req}: {count}")
        
        if 'strategic_questions' in result:
            console.print("\n[bold]Strategic Interview Questions:[/bold]")
            for i, q in enumerate(result['strategic_questions'], 1):
                console.print(f"  {i}. {q}")
        
        if 'interview_process' in result and result['interview_process']:
            console.print("\n[bold]Interview Process:[/bold]")
            for stage in result['interview_process'].get('stages', []):
                console.print(f"  • {stage}")
        
        if 'tech_stack_focus' in result:
            console.print("\n[bold]Tech Stack Focus:[/bold]")
            for tech, count in list(result['tech_stack_focus'].items())[:10]:
                console.print(f"  • {tech}: {count}")
    
    asyncio.run(_company())


@app.command()
def companies(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of companies"),
    min_jobs: int = typer.Option(3, "--min-jobs", help="Minimum relevant jobs"),
):
    """List top companies by relevant job count"""
    console.print(Panel.fit("🏆 [bold]Top Companies[/bold]", border_style="green"))
    
    async def _companies():
        with console.status("Generating report..."):
            report = await intel_service.get_top_companies_report(limit=limit)
        
        if not report:
            console.print("No companies found. Run a scan first.")
            return
        
        table = Table()
        table.add_column("Rank", style="dim", width=5)
        table.add_column("Company", style="cyan", width=30)
        table.add_column("Relevant Jobs", style="green", width=12)
        table.add_column("Total Jobs", style="blue", width=10)
        table.add_column("Top Tech", style="yellow", width=35)
        table.add_column("Rating", style="magenta", width=8)
        
        for i, c in enumerate(report, 1):
            if c['relevant_jobs'] < min_jobs:
                continue
            top_tech = ", ".join(list(c['top_tech'].keys())[:5])
            table.add_row(
                str(i),
                c['company'][:28],
                str(c['relevant_jobs']),
                str(c['total_jobs']),
                top_tech[:33],
                f"{c['glassdoor_rating']:.1f}" if c['glassdoor_rating'] else "N/A",
            )
        
        console.print(table)
    
    asyncio.run(_companies())


@app.command()
def tech_search(
    technologies: List[str] = typer.Argument(..., help="Technologies to search for"),
    min_jobs: int = typer.Option(2, "--min-jobs", help="Minimum relevant jobs"),
):
    """Find companies hiring for specific technologies"""
    console.print(Panel.fit(f"🔍 [bold]Companies hiring for: {', '.join(technologies)}[/bold]", border_style="blue"))
    
    async def _tech_search():
        with console.status("Searching..."):
            results = await intel_service.find_companies_by_tech(technologies, min_jobs)
        
        if not results:
            console.print("No matching companies found.")
            return
        
        table = Table()
        table.add_column("Company", style="cyan", width=30)
        table.add_column("Match Score", style="green", width=12)
        table.add_column("Relevant Jobs", style="blue", width=12)
        table.add_column("Matching Tech", style="yellow", width=30)
        table.add_column("All Tech", style="dim", width=40)
        
        for r in results[:20]:
            table.add_row(
                r['company'][:28],
                f"{r['match_score']:.0%}",
                str(r['relevant_jobs']),
                ", ".join(r['matching_technologies']),
                ", ".join(list(r['all_technologies'])[:8]),
            )
        
        console.print(table)
    
    asyncio.run(_tech_search())


@app.command()
def profile():
    """View and edit candidate profile"""
    console.print(Panel.fit("👤 [bold]Candidate Profile[/bold]", border_style="blue"))
    
    async def _profile():
        async with db.session() as session:
            repo = UserProfileRepository(session)
            profile = await repo.get_or_create()
        
        table = Table()
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        
        fields = [
            ("Current Role", profile.current_role),
            ("Years Experience", str(profile.years_experience or 0)),
            ("Skills", ", ".join(profile.skills or [])),
            ("Tech Stack", ", ".join(profile.tech_stack or [])),
            ("Target Roles", ", ".join(profile.preferred_roles or [])),
            ("Min Salary", f"${profile.min_salary:,}" if profile.min_salary else "Not set"),
            ("Remote Preference", profile.remote_preference or "Not set"),
            ("Locations", ", ".join(profile.location_preferences or [])),
            ("Visa Sponsorship", "Yes" if profile.visa_sponsorship_needed else "No"),
            ("Excluded Keywords", ", ".join(profile.excluded_keywords or [])),
            ("Deal Breakers", ", ".join(profile.deal_breakers or [])),
        ]
        
        for field, value in fields:
            table.add_row(field, value or "Not set")
        
        console.print(table)
        
        if Confirm.ask("\nEdit profile?"):
            await _setup_profile()
    
    asyncio.run(_profile())


@app.command()
def stats():
    """Show database statistics"""
    console.print(Panel.fit("📊 [bold]Database Statistics[/bold]", border_style="green"))
    
    async def _stats():
        async with db.session() as session:
            from sqlalchemy import select, func
            from src.db.models import Channel, Company, Job, Message
            
            channels = await session.execute(select(func.count(Channel.id)))
            companies = await session.execute(select(func.count(Company.id)))
            jobs = await session.execute(select(func.count(Job.id)))
            messages = await session.execute(select(func.count(Message.id)))
            relevant = await session.execute(
                select(func.count(Job.id)).where(Job.relevance_score >= 0.7)
            )
            
            by_level = await session.execute(
                select(Job.relevance_level, func.count(Job.id))
                .group_by(Job.relevance_level)
            )
        
        table = Table()
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="magenta")
        
        table.add_row("Channels", str(channels.scalar()))
        table.add_column("Companies", style="cyan")
        table.add_row("Companies", str(companies.scalar()))
        table.add_row("Total Jobs", str(jobs.scalar()))
        table.add_row("Relevant Jobs (≥0.7)", str(relevant.scalar()))
        table.add_row("Messages Stored", str(messages.scalar()))
        
        console.print(table)
        
        console.print("\n[bold]Relevance Distribution:[/bold]")
        level_table = Table()
        level_table.add_column("Level", style="cyan")
        level_table.add_column("Count", style="magenta")
        for level, count in by_level.all():
            level_table.add_row(str(level), str(count))
        console.print(level_table)
    
    asyncio.run(_stats())


@app.command()
def export(
    company: str = typer.Argument(..., help="Company name"),
    format: str = typer.Option("json", "--format", "-f", help="Export format (json/markdown)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file"),
):
    """Export company intelligence report"""
    console.print(f"📄 Exporting report for {company}...")
    
    async def _export():
        with console.status("Generating report..."):
            intel = await intel_service.get_interview_prep(company)
        
        if "error" in intel:
            console.print(f"❌ {intel['error']}")
            return
        
        if format == "json":
            content = json.dumps(intel, indent=2, default=str)
        else:
            content = _generate_markdown_report(intel)
        
        if output:
            with open(output, 'w') as f:
                f.write(content)
            console.print(f"✅ Exported to {output}")
        else:
            console.print(content)
    
    def _generate_markdown_report(data: dict) -> str:
        lines = [f"# Company Intelligence Report: {data.get('company', 'Unknown')}", ""]
        
        if data.get('relevant_jobs'):
            lines.append(f"**Relevant Jobs Found:** {data['relevant_jobs']}")
            lines.append("")
        
        if data.get('common_requirements'):
            lines.append("## Common Requirements")
            for req, count in data['common_requirements'].items():
                lines.append(f"- {req} ({count} mentions)")
            lines.append("")
        
        if data.get('strategic_questions'):
            lines.append("## Strategic Interview Questions")
            for i, q in enumerate(data['strategic_questions'], 1):
                lines.append(f"{i}. {q}")
            lines.append("")
        
        if data.get('interview_process'):
            lines.append("## Interview Process")
            for stage in data['interview_process'].get('stages', []):
                lines.append(f"- {stage}")
            lines.append("")
        
        return "\n".join(lines)
    
    asyncio.run(_export())


if __name__ == "__main__":
    app()