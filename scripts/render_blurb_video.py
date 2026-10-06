#!/usr/bin/env python3
"""Render a simple narrated TikTok video from the daily Libri-blurb slideshow."""
from __future__ import annotations

import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, wave
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps

WORKSPACE = Path(__file__).resolve().parent.parent
DEFAULT_ELEVENLABS_VOICE = "pFZP5JQG7iQjIQuC4Bku"  # Lily – Velvety Actress

def load_env() -> dict[str, str]:
    values = dict(os.environ)
    path = WORKSPACE / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values

def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def speak_sapi(text: str, wav: Path) -> None:
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v=$s.GetInstalledVoices() | ? {$_.VoiceInfo.Culture.Name -like 'de-*'} | select -First 1; "
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)}; "
          f"$s.SetOutputToWaveFile('{str(wav).replace(chr(39), chr(39)*2)}'); "
          f"$s.Speak('{text.replace(chr(39), chr(39)*2)}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], check=True)

def speak_piper(text: str, wav: Path) -> tuple[str, dict | None]:
    """Use the local open-source Piper voice, with SAPI as a fallback."""
    piper_root = WORKSPACE / ".tools" / "piper"
    model = WORKSPACE / ".tools" / "piper-voices" / "de_DE-thorsten-high.onnx"
    if piper_root.exists() and model.exists():
        sys.path.insert(0, str(piper_root))
        from piper import PiperVoice, SynthesisConfig
        voice = PiperVoice.load(model)
        with wave.open(str(wav), "wb") as handle:
            voice.synthesize_wav(text, handle, syn_config=SynthesisConfig(length_scale=1.06))
        return "piper/de_DE-thorsten-high", None
    speak_sapi(text, wav)
    return "windows-sapi", None

def speak_elevenlabs(text: str, wav: Path, voice_id: str, api_key: str) -> tuple[str, dict]:
    cache_key = hashlib.sha256(f"{voice_id}|eleven_multilingual_v2|{text}".encode("utf-8")).hexdigest()
    cache_dir = WORKSPACE / ".automation" / "tts_cache"
    cache_wav = cache_dir / f"{cache_key}.wav"
    cache_alignment = cache_dir / f"{cache_key}.json"
    if cache_wav.exists() and cache_alignment.exists():
        shutil.copy2(cache_wav, wav)
        return f"elevenlabs/{voice_id}/eleven_multilingual_v2", json.loads(cache_alignment.read_text(encoding="utf-8"))
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=pcm_22050"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.56, "similarity_boost": 0.78, "style": 0.18, "use_speaker_boost": True},
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    pcm = base64.b64decode(result["audio_base64"])
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(pcm)
    alignment = result.get("alignment") or result.get("normalized_alignment") or {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav, cache_wav)
    cache_alignment.write_text(json.dumps(alignment, ensure_ascii=False), encoding="utf-8")
    return f"elevenlabs/{voice_id}/eleven_multilingual_v2", alignment

def load_remote_image(url: str) -> Image.Image | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "TikTokShop-Libri-Automation/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(8_000_000)
        with Image.open(BytesIO(payload)) as source:
            return ImageOps.exif_transpose(source).convert("RGB")
    except Exception:
        return None

def fullscreen_book_image(source: Image.Image) -> Image.Image:
    # True full bleed: crop the supplied product photo to 9:16. The central
    # book remains dominant and there are no template-like borders.
    return ImageOps.fit(source, (1080, 1920), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def write_subtitles(text: str, duration: float, destination: Path) -> None:
    words = text.split()
    chunks = [" ".join(words[index:index + 7]) for index in range(0, len(words), 7)]
    weights = [max(1, len(chunk)) for chunk in chunks]
    total = sum(weights)
    cursor = 0.0
    entries: list[str] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
        span = duration * weight / total
        end = min(duration, cursor + span)
        entries.append(f"{index}\n{srt_time(cursor)} --> {srt_time(end)}\n{chunk}\n")
        cursor = end
    destination.write_text("\n".join(entries), encoding="utf-8")

def write_aligned_subtitles(alignment: dict, destination: Path) -> bool:
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not characters or not (len(characters) == len(starts) == len(ends)):
        return False
    aligned_text = "".join(characters)
    words = list(re.finditer(r"\S+", aligned_text))
    groups = [words[index:index + 5] for index in range(0, len(words), 5)]
    entries: list[str] = []
    for number, group in enumerate(groups, start=1):
        first, last = group[0], group[-1]
        caption = aligned_text[first.start():last.end()]
        start_time = 0.0 if number == 1 else float(starts[first.start()])
        # Keep each caption visible until the next one starts. ElevenLabs can
        # insert natural pauses between phrases; ending at the last phoneme
        # made captions appear to vanish during those pauses.
        if number < len(groups):
            next_first = groups[number][0]
            end_time = float(starts[next_first.start()])
        else:
            end_time = float(ends[-1])
        entries.append(
            f"{number}\n{srt_time(start_time)} --> {srt_time(end_time)}\n{caption}\n"
        )
    destination.write_text("\n".join(entries), encoding="utf-8")
    return True

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seconds-per-slide", type=float, default=3.2)
    p.add_argument("--tts", choices=("auto", "elevenlabs", "piper"), default="auto")
    p.add_argument("--voice-id", default="")
    args = p.parse_args()
    args.manifest = args.manifest.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    photos = [Path(x) for x in manifest["photos"]]
    # The title remains visual on the end card. Starting directly with the
    # plot avoids awkward pronunciation of English book titles.
    narration = manifest.get("spoken_text", "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blurb-video-") as td:
        td = Path(td)
        wav = td / "voice.wav"
        environment = load_env()
        eleven_key = environment.get("ELEVENLABS_API_KEY", "")
        use_elevenlabs = args.tts == "elevenlabs" or (args.tts == "auto" and bool(eleven_key))
        if use_elevenlabs:
            if not eleven_key:
                raise RuntimeError("ELEVENLABS_API_KEY fehlt in .env")
            voice_name, alignment = speak_elevenlabs(
                narration, wav, args.voice_id or environment.get("ELEVENLABS_VOICE_ID", "") or DEFAULT_ELEVENLABS_VOICE, eleven_key
            )
        else:
            voice_name, alignment = speak_piper(narration, wav)
        gallery_frames: list[Path] = []
        for index, url in enumerate(manifest.get("gallery_sources") or []):
            source = load_remote_image(url)
            if source is None:
                continue
            frame = td / f"gallery-{index:02d}.jpg"
            fullscreen_book_image(source).save(frame, quality=95)
            gallery_frames.append(frame)
            if len(gallery_frames) >= 6:
                break
        if not gallery_frames:
            with Image.open(photos[0]).convert("RGB") as source:
                frame = td / "cover-fullscreen.jpg"
                fullscreen_book_image(source).save(frame, quality=95)
                gallery_frames.append(frame)
        concat = td / "images.txt"
        with wave.open(str(wav), "rb") as handle:
            voice_seconds = handle.getnframes() / max(1, handle.getframerate())
        subtitles = td / "subtitles.srt"
        if not alignment or not write_aligned_subtitles(alignment, subtitles):
            write_subtitles(narration, voice_seconds, subtitles)
        shutil.copy2(subtitles, args.output.with_suffix(".srt"))
        end_seconds = 3.0
        image_seconds = max((voice_seconds - end_seconds) / len(gallery_frames), 2.5)
        def q(path: Path) -> str:
            return path.as_posix().replace("'", "'\\''")
        lines = []
        for frame in gallery_frames:
            lines += [f"file '{q(frame)}'", f"duration {image_seconds}"]
        lines += [f"file '{q(photos[-1])}'", f"duration {end_seconds}", f"file '{q(photos[-1])}'"]
        concat.write_text("\n".join(lines), encoding="utf-8")
        subtitle_filter = "subtitles=subtitles.srt:force_style='FontName=Arial,FontSize=9,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=105'"
        cmd = [ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(wav),
               # Expand the still-image timeline to real video frames before
               # rendering subtitles. Otherwise libass only refreshes text at
               # image changes and intermediate captions never appear.
               "-vf", f"fps=30,{subtitle_filter},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
               "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k", "-shortest", str(args.output)]
        subprocess.run(cmd, cwd=td, check=True)
    print(f"Video: {args.output.resolve()}")
    print(f"Voice: {voice_name} | Gallery images: {len(gallery_frames)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
