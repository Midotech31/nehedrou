"""Technical media fixtures, never therapeutic models or deliverables."""
import io
import wave

def pcm_fixture():
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        import math, struct
        stream.writeframes(b''.join(struct.pack('<h', int(5000 * math.sin(2 * math.pi * 220 * i / 8000))) for i in range(800)))
    return output.getvalue()
