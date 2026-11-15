"""Dedicated scheduled discovery worker. Run as a separate Railway service."""
import asyncio, logging, signal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings
from app.database import Base,engine,SessionLocal
from app.sources import discover

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
log=logging.getLogger("opportunity-worker")
async def scan():
    db=SessionLocal()
    try:
        result=await discover(db)
        log.info("Discovery completed: %s",result)
        return result
    except Exception:
        log.exception("Discovery scan failed")
        db.rollback()
        raise
    finally:db.close()

async def main():
    if engine is not None:
        Base.metadata.create_all(bind=engine)
    await scan()
    if not settings.enable_scheduler:
        log.info("ENABLE_SCHEDULER is false; completed one scan and exiting.")
        return
    scheduler=AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(scan,"interval",minutes=max(30,settings.scan_interval_minutes),
                      id="opportunity-discovery",coalesce=True,max_instances=1,
                      misfire_grace_time=900)
    scheduler.start()
    log.info("Worker running; interval=%s minutes",max(30,settings.scan_interval_minutes))
    try:
        while True:await asyncio.sleep(3600)
    finally:scheduler.shutdown(wait=False)

if __name__=="__main__":asyncio.run(main())
