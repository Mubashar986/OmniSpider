from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.scrape_log import ScrapeLog

class ScrapeLogRepository:
    """
    Repository for tracking scrape attempts and enforcing 7-day re-scrape cooldowns.
    """
    def was_scraped_recently(self, db: Session, url: str, days: int = 7) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        latest_log = db.query(ScrapeLog).filter(
            ScrapeLog.url == url,
            ScrapeLog.scraped_at >= cutoff,
            ScrapeLog.status_code == 200
        ).first()
        return latest_log is not None

    def log_scrape_attempt(
        self,
        db: Session,
        url: str,
        domain: str,
        status_code: int,
        engine_used: str,
        error_message: Optional[str] = None
    ) -> ScrapeLog:
        log = ScrapeLog(
            url=url,
            domain=domain,
            status_code=status_code,
            engine_used=engine_used,
            error_message=error_message
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
