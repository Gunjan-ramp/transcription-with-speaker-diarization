import time
import os
import json
import traceback
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.services.graph_service import GraphService
from app.services.transcription_workflow import process_transcription

PROCESSED_FILES_LOG = "processed_files.json"
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "scheduler.log"

# --- Logging Setup ---
def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    
    logger = logging.getLogger("scheduler")
    logger.setLevel(logging.INFO)
    
    # Check if handlers already exist to avoid duplicate logs during reload
    if not logger.handlers:
        # File Handler
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)
        
    return logger

logger = setup_logging()


def load_processed_files():
    if os.path.exists(PROCESSED_FILES_LOG):
        try:
            with open(PROCESSED_FILES_LOG, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()


def save_processed_file(file_id):
    processed = load_processed_files()
    processed.add(file_id)
    with open(PROCESSED_FILES_LOG, "w") as f:
        json.dump(list(processed), f)


# ✅ Make job async
async def job():
    logger.info(f"\n[Job Start] Checking OneDrive at {datetime.now()}...")

    try:
        target_user = settings.target_user_email
        target_folder = settings.onedrive_folder_path

        if not target_user:
            logger.error("Error: TARGET_USER_EMAIL not set in config.")
            return

        graph = GraphService(user_email=target_user)

        # Get today's date string for filtering (ISO format: YYYY-MM-DD)
        today_date_str = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Listing files for {target_user} in '{target_folder}'...")
        all_files = graph.list_files_in_folder(target_folder)

        if not all_files:
            logger.info("No files found or error listing files.")
            return

        # Filter for today's recordings and sort by creation date descending
        # We also filter by extension here to be cleaner
        files = []
        for f in all_files:
            file_name = f.get("name")
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in settings.allowed_extensions:
                continue
                
            created_str = f.get("createdDateTime")
            if not created_str:
                continue
                
            # createdDateTime is UTC, e.g. 2026-02-24T08:01:28Z
            if not created_str.startswith(today_date_str):
                continue
                
            files.append(f)

        # Sort files by createdDateTime descending (latest first)
        files.sort(key=lambda x: x.get("createdDateTime", ""), reverse=True)

        if not files:
            logger.info(f"No recordings found for today ({today_date_str}).")
            return

        logger.info(f"Found {len(files)} recordings for today. Processing latest first.")

        processed_ids = load_processed_files()

        for file in files:
            file_id = file.get("id")
            file_name = file.get("name")

            if file_id in processed_ids:
                continue

            logger.info(f"Found new file: {file_name} (ID: {file_id})")

            temp_download_path = f"temp_od_{file_name}"

            try:
                logger.info(f"Downloading {file_name}...")
                if graph.download_file(file_id, temp_download_path):

                    logger.info("Starting transcription...")

                    # ✅ NO asyncio.run() here
                    result = await process_transcription(
                        temp_download_path,
                        save_files=True
                    )

                    mom_path = result.get("saved_files", {}).get("mom_md")
                    formatted_transcript_path = result.get("saved_files", {}).get("formatted_md")

                    if mom_path and os.path.exists(mom_path):
                        with open(mom_path, "r", encoding="utf-8") as f:
                            mom_content_md = f.read()
                        # Convert Markdown to HTML
                        import markdown
                        mom_content_html = markdown.markdown(mom_content_md, extensions=['tables', 'nl2br'])
                    else:
                        mom_content_html = "<p>Minutes of Meeting could not be generated.</p>"

                    email_body = f"""
                    <h2>Meeting Transcription Complete</h2>
                    <p><b>File:</b> {file_name}</p>
                    <p><b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                    <hr>
                    <h3>Meeting Minutes</h3>
                    <div style="font-family: sans-serif;">
                    {mom_content_html}
                    </div>
                    """

                    logger.info("Sending email...")
                    if settings.manager_email and settings.sender_email:
                        # attachments = []
                        # if formatted_transcript_path:
                        #     attachments.append(formatted_transcript_path)

                        graph.send_email(
                            to_email=settings.manager_email,
                            subject=f"MOM of Today's meeting",
                            content=email_body,
                            attachment_paths=[] # No attachments
                        )
                    else:
                        logger.warning("Skipping email: MANAGER_EMAIL or SENDER_EMAIL not set.")

                    save_processed_file(file_id)
                    logger.info(f"Successfully processed {file_name}")

                else:
                    logger.error(f"Failed to download {file_name}")

            except Exception as e:
                logger.error(f"Error processing {file_name}: {e}")
                traceback.print_exc()

            finally:
                if os.path.exists(temp_download_path):
                    try:
                        os.remove(temp_download_path)
                    except:
                        pass

    except Exception as e:
        logger.error(f"Job failed: {e}")
        traceback.print_exc()


# ✅ Exportable start function
def start_scheduler():
    logger.info("Starting Scheduler...")
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    trigger = CronTrigger(
        day_of_week="mon-fri",
        hour=17,
        minute=45,
        timezone="Asia/Kolkata"
    )

    scheduler.add_job(job, trigger)
    scheduler.start()
    
    logger.info(f"Scheduler started. Job scheduled for: {trigger}")
    return scheduler

# ✅ Async main entry for manual testing
async def main():
    scheduler = start_scheduler()
    print("Press Ctrl+C to exit.")
    
    # Keep event loop alive
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
