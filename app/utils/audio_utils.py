import base64
import mimetypes

def audio_to_data_url(file_path: str):

    mime_type, _ = mimetypes.guess_type(file_path)

    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded}"