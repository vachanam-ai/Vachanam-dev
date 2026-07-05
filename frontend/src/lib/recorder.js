// Mic → 16-bit PCM WAV recorder for voice-clone samples (Vinay 2026-07-05:
// clinics record one voice per language right in Settings). WAV, not
// MediaRecorder's webm/opus — smallest.ai's clone API wants a plain audio file
// and WAV works everywhere with zero server transcoding.
// ponytail: ScriptProcessorNode (deprecated but universal); AudioWorklet if
// browsers ever drop it.

export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(proc);
  proc.connect(ctx.destination);

  return {
    stop: async () => {
      proc.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      const sampleRate = ctx.sampleRate;
      await ctx.close();
      const n = chunks.reduce((s, c) => s + c.length, 0);
      const pcm = new Int16Array(n);
      let off = 0;
      for (const c of chunks) {
        for (let i = 0; i < c.length; i++) {
          const s = Math.max(-1, Math.min(1, c[i]));
          pcm[off++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
      }
      const buf = new ArrayBuffer(44 + pcm.length * 2);
      const v = new DataView(buf);
      const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
      str(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE");
      str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
      v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
      v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
      str(36, "data"); v.setUint32(40, pcm.length * 2, true);
      new Int16Array(buf, 44).set(pcm);
      const blob = new Blob([buf], { type: "audio/wav" });
      return {
        file: new File([blob], "clinic-voice.wav", { type: "audio/wav" }),
        url: URL.createObjectURL(blob),
        seconds: n / sampleRate
      };
    }
  };
}
