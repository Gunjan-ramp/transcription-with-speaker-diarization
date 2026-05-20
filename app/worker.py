import argparse
import asyncio
import os
import sys
from app.services.meeting_bot import TeamsBot
from app.services.transcription_workflow import process_transcription
from app.core.config import settings
from app.services.graph_service import GraphService
from datetime import datetime
import markdown

async def run_worker(meeting_url: str, bot_name: str, duration_minutes: int):
    print(f"[Worker] Starting bot for {meeting_url}")
    bot = TeamsBot(meeting_url, bot_name)
    
    # Run the bot (blocking, so we use run_in_executor if needed, but here we can just run it)
    loop = asyncio.get_event_loop()
    audio_file_path = await loop.run_in_executor(None, bot.join_and_record, duration_minutes)
    
    if audio_file_path and os.path.exists(audio_file_path):
        print(f"[Worker] Recording finished. Starting transcription...")
        result = await process_transcription(audio_file_path, save_files=True)
        
        if settings.manager_email:
            print(f"[Worker] Sending summary email to {settings.manager_email}...")
            graph = GraphService(user_email=settings.target_user_email)
            mom_path = result.get("saved_files", {}).get("mom_md")
            mom_content = "Minutes could not be generated."
            if mom_path and os.path.exists(mom_path):
                with open(mom_path, "r", encoding="utf-8") as f:
                    mom_content = f.read()
            
            html_content = markdown.markdown(mom_content, extensions=['tables', 'nl2br'])
            
            email_body = f"""
            <h2>Meeting Bot: Complete</h2>
            <p><b>Meeting URL:</b> {meeting_url}</p>
            <hr>{html_content}
            """
            graph.send_email(
                to_email=settings.manager_email,
                subject=f"Bot Result: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                content=email_body
            )
        print("[Worker] Task completed successfully.")
    else:
        print("[Worker] Bot stopped or no audio captured.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a single meeting bot worker.")
    parser.add_argument("--url", required=True, help="The Teams meeting URL")
    parser.add_argument("--name", default="AI Assistant", help="The name of the bot")
    parser.add_argument("--duration", type=int, default=60, help="Duration in minutes")
    
    args = parser.parse_args()
    
    asyncio.run(run_worker(args.url, args.name, args.duration))
