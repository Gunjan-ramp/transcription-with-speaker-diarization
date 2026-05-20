from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
import os
import asyncio
from app.services.meeting_bot import TeamsBot
from app.services.transcription_workflow import process_transcription
from app.core.config import settings
from app.services.graph_service import GraphService
from datetime import datetime

router = APIRouter(prefix="/bot", tags=["Meeting Bot"])

# Global tracker for running bots
running_bots = {}

class BotJoinRequest(BaseModel):
    meeting_url: str
    bot_name: str = "AI Assistant"
    duration_minutes: int = 60

async def run_bot_task(meeting_id: str, meeting_url: str, bot_name: str, duration_minutes: int):
    if settings.use_docker_isolation:
        print(f"[Bot Task] Spawning isolated Docker container for {meeting_url}")
        try:
            import docker
            client = docker.from_env()
            
            # Prepare volumes if host paths are provided
            volumes = {}
            if settings.docker_host_output_path:
                volumes[settings.docker_host_output_path] = {"bind": "/app/output", "mode": "rw"}
            if settings.docker_host_env_path:
                volumes[settings.docker_host_env_path] = {"bind": "/app/.env", "mode": "ro"}
            
            # Start the container
            container_name = f"bot-meeting-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            container = client.containers.run(
                image=settings.docker_image,
                name=container_name,
                command=[
                    "python", "-m", "app.worker",
                    "--url", meeting_url,
                    "--name", bot_name,
                    "--duration", str(duration_minutes)
                ],
                volumes=volumes,
                detach=True,
                remove=True, # Remove container when it finishes
                environment={
                    "RUN_MAIN": "false", # Prevent starting the main app
                },
                # Essential for stability
                ipc_mode="host",
                shm_size="2g"
            )
            print(f"[Bot Task] Container name: {container_name}")
            print(f"[Bot Task] Container started: {container.id}")
        except Exception as e:
            print(f"[Bot Task] Failed to spawn Docker container: {e}")
            # Fallback to in-process? Or just fail?
            # For now, let's just log the error.
    else:
        bot = TeamsBot(meeting_url, bot_name)
        running_bots[meeting_id] = bot
        
        print(f"[Bot Task] Starting bot for {meeting_url} (in-process)")
        
        try:
            loop = asyncio.get_event_loop()
            audio_file_path = await loop.run_in_executor(None, bot.join_and_record, duration_minutes)
            
            if audio_file_path and os.path.exists(audio_file_path):
                print(f"[Bot Task] Recording finished. Starting transcription...")
                result = await process_transcription(audio_file_path, save_files=True)
                
                if settings.manager_email:
                    graph = GraphService(user_email=settings.target_user_email)
                    mom_path = result.get("saved_files", {}).get("mom_md")
                    mom_content = "Minutes could not be generated."
                    if mom_path and os.path.exists(mom_path):
                        with open(mom_path, "r", encoding="utf-8") as f:
                            mom_content = f.read()
                    
                    import markdown
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
            else:
                print("[Bot Task] Bot stopped or no audio captured.")
        finally:
            if meeting_id in running_bots:
                del running_bots[meeting_id]

@router.post("/join")
async def join_meeting(request: BotJoinRequest, background_tasks: BackgroundTasks):
    meeting_id = datetime.now().strftime("%H%M%S")
    background_tasks.add_task(run_bot_task, meeting_id, request.meeting_url, request.bot_name, request.duration_minutes)
    return {"status": "Bot starting", "bot_id": meeting_id, "url": request.meeting_url}

@router.post("/stop")
async def stop_bot():
    """
    Force stop all running bots.
    """
    if not running_bots:
        return {"message": "No bots are currently running."}
    
    count = 0
    for bot_id, bot in list(running_bots.items()):
        bot.stop() # Trigger the stop flag
        count += 1
    
    return {"message": f"Stop signal sent to {count} bot(s). Processing will start shortly."}
