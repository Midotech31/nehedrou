"""Technical media fixtures, never therapeutic models or deliverables."""
import io
import wave

def pcm_fixture():
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b'\x00\x00' * 800)
    return output.getvalue()
