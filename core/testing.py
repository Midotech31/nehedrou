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


def practice_form_data(client, path, data=None):
    """Obtain a real form scope for tests without bypassing production validation."""
    response = client.get(path)
    if response.status_code != 200:
        raise AssertionError('Practice form GET did not succeed: %s' % response.status_code)
    values = data.copy() if data is not None else {}
    values['practice_scope'] = response.context['practice_scope']
    return values
