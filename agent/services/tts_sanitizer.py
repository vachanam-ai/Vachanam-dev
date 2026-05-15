import re
import unicodedata


def sanitize_for_tts(text: str) -> str:
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'^\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'#(\d+)', r'\1', text)
    text = re.sub(r'^(\d+)\.\s+', r'\1 ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-\s+', '', text, flags=re.MULTILINE)
    text = _strip_emoji(text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def _strip_emoji(text: str) -> str:
    result = []
    for char in text:
        cat = unicodedata.category(char)
        if cat[0] == 'S' and cat != 'Sc':
            continue
        result.append(char)
    return ''.join(result)
