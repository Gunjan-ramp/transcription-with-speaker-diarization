def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def timestamp_to_seconds(timestamp: str) -> float:
    """
    Convert VTT timestamp (HH:MM:SS.mmm) to seconds.
    
    Args:
        timestamp: String like "00:01:23.456"
    
    Returns:
        Float seconds
    """
    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    
    return hours * 3600 + minutes * 60 + seconds
