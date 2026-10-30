"""Bounded structural validation. This does not validate clinical audio quality."""
import hashlib
import io
import warnings
import wave
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from PIL import Image, UnidentifiedImageError
from mutagen import MutagenError
from mutagen.mp3 import MP3

MAX_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 16_000_000


def validate_media(file, kind):
    if kind not in ['image', 'audio']:
        raise ValidationError(_('The file type must match the selected media kind.'))
    extension = file.name.rsplit('.', 1)[-1].lower()
    if extension not in ['png', 'jpg', 'jpeg', 'webp', 'wav', 'mp3']:
        raise ValidationError(_('Use a PNG, JPEG, WebP, WAV or MP3 file.'))
    if (extension in ['png', 'jpg', 'jpeg', 'webp']) != (kind == 'image'):
        raise ValidationError(_('The file type must match the selected media kind.'))
    try:
        file.seek(0)
        data = file.read(MAX_BYTES + 1)
    finally:
        file.seek(0)
    if len(data) > MAX_BYTES:
        raise ValidationError(_('The file must be smaller than 15 MB.'))
    metadata = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    try:
        if kind == 'image':
            expected = {'png': 'PNG', 'webp': 'WEBP'}.get(extension, 'JPEG')
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data), formats=[expected]) as image:
                    width, height = image.size
                    if width * height > MAX_PIXELS or width > 6000 or height > 6000:
                        raise ValidationError(_('Images must not exceed 6000 pixels per side or 16 million pixels.'))
                    image.verify()
                # verify() alone does not decode JPEG data; load it separately.
                with Image.open(io.BytesIO(data), formats=[expected]) as image:
                    image.load()
                metadata.update(format=expected, width=width, height=height)
        elif extension == 'wav':
            with wave.open(io.BytesIO(data), 'rb') as audio:
                rate, channels, width, frames = audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()
                if rate <= 0 or channels not in [1, 2] or width not in [1, 2, 3, 4] or len(audio.readframes(frames)) != frames * channels * width:
                    raise ValueError('Incomplete PCM data')
                duration = frames / rate
                if not 0.05 <= duration <= 60 or not 8000 <= rate <= 96000:
                    raise ValidationError(_('Audio models must last between 0.05 and 60 seconds, with a supported sample rate.'))
                metadata.update(format='WAV', seconds=round(duration, 4), channels=channels, sample_rate=rate)
                from .audio_signal import pcm_levels
                metadata['signal'] = pcm_levels(data, width, channels)
        else:
            info = MP3(io.BytesIO(data)).info
            if info.sketchy or info.channels not in [1, 2] or not 8000 <= info.sample_rate <= 96000:
                raise ValueError('Incomplete MPEG stream')
            if not 0.05 <= info.length <= 60:
                raise ValidationError(_('Audio models must last between 0.05 and 60 seconds, with a supported sample rate.'))
            metadata.update(format='MP3', seconds=round(info.length, 4), channels=info.channels, sample_rate=info.sample_rate)
    except ValidationError:
        raise
    except (OSError, EOFError, ValueError, SyntaxError, wave.Error, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, MutagenError):
        raise ValidationError(_('This media file is incomplete or unreadable. Upload a valid file.'))
    return metadata
