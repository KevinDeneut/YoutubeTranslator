"""
Translate text using argos-translate (fully offline, no API key).
Language model packages are downloaded on first use per language pair.
"""
import asyncio

import argostranslate.package
import argostranslate.translate


def ensure_language_pair(source_lang: str, target_lang: str) -> None:
    """Public alias — pre-install translation packages before the pipeline starts."""
    _ensure_language_pair(source_lang, target_lang)


def _ensure_language_pair(source_lang: str, target_lang: str) -> None:
    """Download and install the translation package if not already present."""
    installed = argostranslate.translate.get_installed_languages()
    installed_codes = {lang.code for lang in installed}

    if source_lang in installed_codes and target_lang in installed_codes:
        # Check if the direct translation path exists
        src = next((l for l in installed if l.code == source_lang), None)
        if src:
            translations = src.translations_to
            if any(t.to_lang.code == target_lang for t in translations):
                return  # Already installed

    # Download missing packages
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()

    for pkg in available:
        if pkg.from_code == source_lang and pkg.to_code == target_lang:
            print(f"[translate] Installing {source_lang} -> {target_lang} model...")
            argostranslate.package.install_from_path(pkg.download())
            return

    # If direct pair not found, try via English as pivot
    if source_lang != "en" and target_lang != "en":
        _ensure_language_pair(source_lang, "en")
        _ensure_language_pair("en", target_lang)


def _translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """Translate a single text string."""
    if source_lang == target_lang:
        return text

    _ensure_language_pair(source_lang, target_lang)

    installed = argostranslate.translate.get_installed_languages()
    src = next((l for l in installed if l.code == source_lang), None)
    tgt = next((l for l in installed if l.code == target_lang), None)

    if not src or not tgt:
        raise ValueError(f"Language pair {source_lang}->{target_lang} not available")

    translation = src.get_translation(tgt)
    if not translation:
        # Try pivot via English
        en = next((l for l in installed if l.code == "en"), None)
        if en and src and tgt:
            step1 = src.get_translation(en)
            step2 = en.get_translation(tgt)
            if step1 and step2:
                return step2.translate(step1.translate(text))
        raise ValueError(f"No translation path for {source_lang}->{target_lang}")

    return translation.translate(text)


async def translate_segments(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    progress_cb=None,
) -> list[dict]:
    """
    Translate a list of transcription segments.
    Each segment: {"start": float, "end": float, "text": str}
    Returns same list with "translated_text" added.
    """
    loop = asyncio.get_event_loop()

    def _run():
        # Install language models once upfront
        _ensure_language_pair(source_lang, target_lang)

        result = []
        total = len(segments)
        for i, seg in enumerate(segments):
            translated = _translate_text(seg["text"], source_lang, target_lang)
            result.append({**seg, "translated_text": translated})
            if progress_cb:
                pct = round((i + 1) / total * 100)
                progress_cb(f"Translating: {i + 1}/{total} ({pct}%)")
        return result

    return await loop.run_in_executor(None, _run)


async def translate_single(text: str, source_lang: str, target_lang: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _translate_text, text, source_lang, target_lang
    )
