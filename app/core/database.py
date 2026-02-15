from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Text,
    Date,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from .config import settings  # Updated import
import urllib.parse
import traceback

from sqlalchemy.ext.declarative import DeferredReflection

# Inherit from DeferredReflection to allow runtime schema loaded
class Base(DeferredReflection, declarative_base()):
    __abstract__ = True


# =========================================================
# ORM MODELS
# =========================================================

class Meeting(Base):
    __tablename__ = "Meetings"
    # Columns and relationships are loaded from database via reflection

class Participant(Base):
    __tablename__ = "Participants"

class ActionItem(Base):
    __tablename__ = "ActionItems"

class EmailLog(Base):
    __tablename__ = "EmailLogs"


# =========================================================
# DATABASE ENGINE / SESSION
# =========================================================

engine = None
SessionLocal = None


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():
    """
    Initializes database connection using SQL Server Authentication only.
    Automatically creates database and tables if missing.
    """
    global engine, SessionLocal

    try:
        print(f"Connecting to SQL Server at {settings.db_server}...")

        # -------------------------------
        # APPLICATION DATABASE CONNECTION
        # -------------------------------
        print(f"Connecting to database '{settings.db_name}'...")


        # -------------------------------
        # APPLICATION DATABASE CONNECTION
        # -------------------------------
        db_params = urllib.parse.quote_plus(
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.db_server};"
            f"DATABASE={settings.db_name};"
            f"UID={settings.db_user};"
            f"PWD={settings.db_password};"
            "TrustServerCertificate=yes;"
        )

        engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={db_params}",
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )

        # Base.metadata.create_all(bind=engine)
        print(f"Connecting to SQL Server at {settings.db_server} for schema reflection...")
        
        # Prepare definitions from database
        Base.prepare(engine)
        print("[+] Database schema successfully reflected.")

    except Exception:
        print("!!! DATABASE INITIALIZATION FAILED !!!")
        traceback.print_exc()
        print(
            f"Server: {settings.db_server}, "
            f"Database: {settings.db_name}, "
            f"Driver: {settings.db_driver}"
        )
        print("Continuing without database support...")
        engine = None
        SessionLocal = None


# =========================================================
# SESSION DEPENDENCY
# =========================================================

def get_db():
    if SessionLocal is None:
        return None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# DATA STORAGE FUNCTION
# =========================================================

def store_meeting_data(
    title: str,
    date: datetime,
    duration_seconds: float,
    audio_path: str,
    transcript_path: str,
    mom_path: str,
    utterances: list,
    action_items: list = None,
    summary_text: str = None,
) -> int | None:
    """
    Store meeting, participants, and action items.
    """
    if SessionLocal is None:
        print("Database not initialized, skipping storage.")
        return None

    session = SessionLocal()

    try:
        meeting = Meeting(
            Title=title,
            MeetingDate=date,
            DurationMinutes=int(duration_seconds // 60),
            AudioFilePath=str(audio_path),
            FormattedTranscriptPath=str(transcript_path),
            MoMFilePath=str(mom_path),
            Notes=summary_text,
        )
        session.add(meeting)
        session.flush()

        meeting_id = meeting.MeetingID

        # Participants
        speakers = {u.get("speaker") for u in utterances if u.get("speaker")}
        for speaker in speakers:
            session.add(
                Participant(
                    MeetingID=meeting_id,
                    Name=speaker,
                    SpeakerLabel=speaker,
                )
            )

        # Action Items
        if action_items:
            for item in action_items:
                session.add(
                    ActionItem(
                        MeetingID=meeting_id,
                        Title=item.get("title", "Untitled Action"),
                        Description=item.get("description", ""),
                        AssignedTo=item.get("assigned_to", ""),
                        Priority=item.get("priority", "Medium"),
                        Status="Open",
                    )
                )

        session.commit()
        print(f"[+] Successfully stored meeting {meeting_id}")
        return meeting_id

    except Exception as e:
        session.rollback()
        print(f"[-] Error storing meeting data: {e}")
        return None

    finally:
        session.close()
