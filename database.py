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
from config import settings
import urllib.parse
import traceback

Base = declarative_base()

# =========================================================
# ORM MODELS
# =========================================================

class Meeting(Base):
    __tablename__ = "Meetings"

    MeetingID = Column(Integer, primary_key=True, autoincrement=True)
    Title = Column(String(255), nullable=False)
    MeetingDate = Column(DateTime, nullable=False)
    DurationMinutes = Column(Integer)

    CalendarEventID = Column(String(255))
    CalendarSource = Column(String(50))

    AudioFilePath = Column(String(500))
    FormattedTranscriptPath = Column(String(500))
    RawJsonPath = Column(String(500))
    MoMFilePath = Column(String(500))

    ProjectName = Column(String(255))
    MeetingType = Column(String(100))
    Notes = Column(Text)

    CreatedAt = Column(DateTime, default=datetime.utcnow)
    UpdatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = relationship(
        "Participant",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )

    action_items = relationship(
        "ActionItem",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )


class Participant(Base):
    __tablename__ = "Participants"

    ParticipantID = Column(Integer, primary_key=True, autoincrement=True)
    MeetingID = Column(Integer, ForeignKey("Meetings.MeetingID"), nullable=False)

    Name = Column(String(255))
    SpeakerLabel = Column(String(50))
    Email = Column(String(255))
    Role = Column(String(100))

    CreatedAt = Column(DateTime, default=datetime.utcnow)

    meeting = relationship("Meeting", back_populates="participants")


class ActionItem(Base):
    __tablename__ = "ActionItems"

    ActionItemID = Column(Integer, primary_key=True, autoincrement=True)
    MeetingID = Column(Integer, ForeignKey("Meetings.MeetingID"), nullable=False)

    Title = Column(String(500), nullable=False)
    Description = Column(Text)
    AssignedTo = Column(String(255))
    DueDate = Column(Date)
    Priority = Column(String(20), default="Medium")
    Status = Column(String(50), default="Open")

    CompletedAt = Column(DateTime)
    CreatedAt = Column(DateTime, default=datetime.utcnow)
    UpdatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    meeting = relationship("Meeting", back_populates="action_items")


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

        from sqlalchemy import text

        # -------------------------------
        # MASTER CONNECTION (for CREATE DB)
        # -------------------------------
        master_params = urllib.parse.quote_plus(
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.db_server};"
            f"UID={settings.db_user};"
            f"PWD={settings.db_password};"
            "TrustServerCertificate=yes;"
        )

        master_engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={master_params}",
            echo=False,
        ).execution_options(isolation_level="AUTOCOMMIT")

        with master_engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM sys.databases WHERE name = :db"),
                {"db": settings.db_name},
            )

            if not result.fetchone():
                print(f"Database '{settings.db_name}' not found. Creating...")
                conn.execute(text(f"CREATE DATABASE [{settings.db_name}]"))
                print(f"Database '{settings.db_name}' created successfully.")
            else:
                print(f"Database '{settings.db_name}' already exists.")

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

        Base.metadata.create_all(bind=engine)
        print("✅ Database connected and tables verified.")

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
        print(f"✅ Successfully stored meeting {meeting_id}")
        return meeting_id

    except Exception as e:
        session.rollback()
        print(f"❌ Error storing meeting data: {e}")
        return None

    finally:
        session.close()
