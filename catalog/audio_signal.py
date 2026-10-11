"""PCM measurements flag recording problems, never clinical appropriateness."""
import io
import math
import wave


def pcm_levels(data, width, channels):
    with wave.open(io.BytesIO(data), 'rb') as audio:
        frames = audio.readframes(audio.getnframes())
    maximum = float(2 ** (width * 8 - 1))
    total = peak = clipping = quiet = 0
    count = len(frames) // width
    for offset in range(0, len(frames), width):
        value = (frames[offset] - 128) if width == 1 else int.from_bytes(frames[offset:offset + width], 'little', signed=True)
        normalized = abs(value) / maximum
        peak = max(peak, normalized)
        total += normalized * normalized
        clipping += normalized >= .999
        quiet += normalized < .001
    rms = math.sqrt(total / max(count, 1))
    return {'peak_dbfs': round(20 * math.log10(max(peak, 1e-6)), 1),
            'rms_dbfs': round(20 * math.log10(max(rms, 1e-6)), 1),
            'silent': peak == 0, 'very_quiet': peak > 0 and rms < .001,
            'clipped_percent': round(100 * clipping / max(count, 1), 3),
            'quiet_percent': round(100 * quiet / max(count, 1), 1)}
