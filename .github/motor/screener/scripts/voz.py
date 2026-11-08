"""Voice-over and subtitles for the Reels (owner, 2 November 2026: "voz y subtítulos, desarrolla").

decir(texto, wav) speaks a line in Spanish into a WAV and returns its seconds. Engines, best first:
  kokoro   Kokoro (Apache 2.0, local, Spanish voices) through kokoro-onnx, when it is installed and its model files are in data/voz/
           (kokoro-v1.0.int8.onnx, voices-v1.0.bin). Not installed yet: downloading them needs the owner's OK.
  windows  the Spanish voice Windows already has (Microsoft Helena, SAPI), through PowerShell. Free and offline, more robotic.
Pista: lines placed in time ([(start, text, with subtitles)]) -> one WAV track for the video, and the subtitle of any instant:
chunks of a few words, timed by their length within the line's real duration (an approximation, enough for a Reel)."""
import array, os, re, subprocess, sys, wave
from common import P

DIR = P("voz")
RATE = 24000                      # every line is converted to 24 kHz mono 16-bit before the track is put together

def motor():
    try:
        import kokoro_onnx  # noqa: F401
        if os.path.exists(os.path.join(DIR, "kokoro-v1.0.int8.onnx")) and os.path.exists(os.path.join(DIR, "voices-v1.0.bin")): return "kokoro"
    except ImportError: pass
    return "windows"

def para_voz(texto):
    """What a line says aloud: "9.075 €" -> "9075 euros", "×12" -> "por 12", "PSA 10" stays, "1ª ed." -> "primera edición"."""
    t = re.sub(r"(\d)\.(\d{3})", r"\1\2", texto)
    t = re.sub(r"(\d[\d,]*)\s*€", r"\1 euros", t); t = re.sub(r"(\d[\d,]*)\s*\$", r"\1 dólares", t)
    t = t.replace("×", "por ").replace("1ª ed.", "primera edición").replace("–", " a ")
    return t

def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def decir(texto, wav, velocidad=1):
    """Speaks texto into wav (24 kHz mono) and returns its duration in seconds."""
    os.makedirs(os.path.dirname(wav), exist_ok=True); crudo = wav + ".raw.wav"
    if motor() == "kokoro":
        import kokoro_onnx, soundfile
        k = kokoro_onnx.Kokoro(os.path.join(DIR, "kokoro-v1.0.int8.onnx"), os.path.join(DIR, "voices-v1.0.bin"))
        audio, sr = k.create(para_voz(texto), voice="ef_dora", speed=1.05 * velocidad, lang="es")
        soundfile.write(crudo, audio, sr)
    else:
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es-*' } | Select-Object -First 1; "
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; $s.Rate = %d; $s.SetOutputToWaveFile($env:PF_WAV); $s.Speak($env:PF_TEXTO); $s.Dispose()" % round(2 + 3 * (velocidad - 1)))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], env={**os.environ, "PF_WAV": crudo, "PF_TEXTO": para_voz(texto)},
                       check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", crudo, "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", wav], check=True)
    os.remove(crudo)
    with wave.open(wav) as w: return w.getnframes() / w.getframerate()

def trozos(texto, n=4):
    """Subtitle chunks of up to n words."""
    w = texto.split(); return [" ".join(w[i:i + n]) for i in range(0, len(w), n)]

class Pista:
    """Lines placed in time. lineas: [(start s, text, subtitles?[, (wav, seconds) already spoken])]; a line that would start before the
    previous one ends waits for it."""
    def __init__(self, lineas, carpeta):
        self.items = []; fin = 0
        for i, (t0, texto, subs, *hecho) in enumerate(lineas):
            if hecho: wav, dur = hecho[0]
            else: wav = os.path.join(carpeta, f"linea{i:02d}.wav"); dur = decir(texto, wav)
            t0 = max(t0, fin + 0.15); fin = t0 + dur
            tz = trozos(texto); tot = sum(len(x) for x in tz) or 1; acc = t0; tiempos = []
            for x in tz: tiempos.append((acc, x)); acc += dur * len(x) / tot
            self.items.append({"t0": t0, "dur": dur, "wav": wav, "texto": texto, "subs": subs, "trozos": tiempos})
        self.fin = fin

    def subtitulo(self, t):
        for it in self.items:
            if it["subs"] and it["t0"] <= t < it["t0"] + it["dur"] + 0.2:
                return next((x for a, x in reversed(it["trozos"]) if a <= t), None)
        return None

    def wav(self, path, duracion):
        """The whole track, duracion seconds long."""
        pcm = array.array("h", bytes(2 * int(RATE * duracion)))
        for it in self.items:
            with wave.open(it["wav"]) as w: s = array.array("h", w.readframes(w.getnframes()))
            o = int(it["t0"] * RATE); n = min(len(s), len(pcm) - o)
            if n > 0: pcm[o:o + n] = s[:n]
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
        return path

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("motor:", motor())
    print(decir(sys.argv[1] if len(sys.argv) > 1 else "La nota lo cambia todo: de 9.075 € sin gradear a 106.918 € en PSA 10.", os.path.join(DIR, "prueba.wav")), "s")
