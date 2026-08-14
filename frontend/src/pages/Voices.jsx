import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, FileAudio, LinkSimple, Microphone, Pause, Play, ShieldCheck, Stop, Trash,
  UploadSimple, Waveform,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import PageHeader from "../components/PageHeader.jsx";
import {
  activateVoiceClone, createVoiceClone, deleteVoiceClone, fetchBranchSettings,
  fetchVoiceClones, getBranchVoices, importVoiceClone, previewVoiceClone, setBranchVoice,
} from "../api/client.js";
import { useAuth } from "../hooks/useAuth.jsx";
import { useConfirm } from "../components/ConfirmDialog.jsx";

const MAX_BYTES = 10 * 1024 * 1024;
const MAX_SECONDS = 20;
const MAX_CUSTOM_VOICES = 1;
const LANGUAGES = [
  { code: "te", label: "Telugu" },
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "ta", label: "Tamil" },
  { code: "kn", label: "Kannada" },
  { code: "ml", label: "Malayalam" },
  { code: "mr", label: "Marathi" },
  { code: "bn", label: "Bengali" },
];

function errorMessage(error, fallback) {
  return error?.response?.data?.detail ?? fallback;
}

function statusLabel(status) {
  if (status === "ready") return "Ready";
  if (status === "failed") return "Needs a new sample";
  if (status === "deleting") return "Deleting";
  return "Preparing voice";
}

function VoiceBars({ active = false }) {
  return <span className={`clone-wave ${active ? "is-active" : ""}`} aria-hidden>{[1, 2, 3, 4, 5, 6, 7].map((bar) => <i key={bar} />)}</span>;
}

function CloneCard({ voice, branchId, playing, onPlay }) {
  const confirm = useConfirm();
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["voice-clones", branchId] });
    qc.invalidateQueries({ queryKey: ["branch-voices", branchId] });
    qc.invalidateQueries({ queryKey: ["branch-settings", branchId] });
  };
  const activate = useMutation({
    mutationFn: () => activateVoiceClone(branchId, voice.id),
    onSuccess: () => { refresh(); toast.success(`${voice.name} is now live`); },
    onError: (error) => toast.error(errorMessage(error, "Could not activate this voice")),
  });
  const remove = useMutation({
    mutationFn: () => deleteVoiceClone(branchId, voice.id),
    onSuccess: () => { refresh(); toast.success("Voice deleted"); },
    onError: (error) => toast.error(errorMessage(error, "Could not delete this voice")),
  });
  const ready = voice.status === "ready";
  return (
    <article className={`clone-card ${voice.active ? "is-selected" : ""}`}>
      <div className="clone-card-visual">
        <span className="clone-avatar"><Waveform size={24} weight="duotone" /></span>
        <VoiceBars active={playing} />
      </div>
      <div className="clone-card-copy">
        <div className="clone-card-title">
          <div><h3>{voice.name}</h3><p>{voice.filename}</p></div>
          <span className={`clone-status is-${voice.status}`}>{statusLabel(voice.status)}</span>
        </div>
        {voice.error_message && <p className="clone-error">{voice.error_message}</p>}
        <div className="clone-card-actions">
          <button type="button" className="clone-play-button" disabled={!ready} onClick={() => onPlay(voice)}>
            {playing ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}
            {playing ? "Pause" : "Preview"}
          </button>
          {voice.active ? (
            <span className="clone-active-label"><Check size={15} weight="bold" /> Active on calls</span>
          ) : (
            <button type="button" className="btn-primary clone-use-button" disabled={!ready || activate.isPending} onClick={() => activate.mutate()}>
              {activate.isPending ? "Applying…" : "Use this voice"}
            </button>
          )}
          <button type="button" className="clone-delete" aria-label={`Delete ${voice.name}`} disabled={remove.isPending || voice.status === "deleting"}
            onClick={async () => {
              if (await confirm({
                title: `Delete “${voice.name}”?`,
                body: "The original recording and the clone are permanently removed from Soniox. This cannot be undone.",
                confirmLabel: "Delete voice",
                destructive: true,
              })) remove.mutate();
            }}>
            <Trash size={17} />
          </button>
        </div>
      </div>
    </article>
  );
}

export default function Voices() {
  const { branchId } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [file, setFile] = useState(null);
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [playingId, setPlayingId] = useState(null);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const audioRef = useRef(null);
  const previewUrl = useMemo(() => file ? URL.createObjectURL(file) : null, [file]);

  useEffect(() => () => {
    clearInterval(timerRef.current);
    recorderRef.current?.state === "recording" && recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    audioRef.current?.pause();
  }, []);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const branch = useQuery({
    queryKey: ["branch-settings", branchId], queryFn: () => fetchBranchSettings(branchId), enabled: Boolean(branchId),
  });
  const catalog = useQuery({
    queryKey: ["branch-voices", branchId, branch.data?.language],
    queryFn: () => getBranchVoices(branchId, branch.data?.language),
    enabled: Boolean(branchId && branch.data),
  });
  const clones = useQuery({
    queryKey: ["voice-clones", branchId], queryFn: () => fetchVoiceClones(branchId), enabled: Boolean(branchId),
    refetchInterval: (query) => query.state.data?.voices?.some((voice) => ["uploading", "processing", "not_computed"].includes(voice.status)) ? 2500 : false,
  });
  const setCatalogVoice = useMutation({
    mutationFn: (voiceId) => setBranchVoice(branchId, voiceId, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["branch-settings", branchId] });
      qc.invalidateQueries({ queryKey: ["voice-clones", branchId] });
      qc.invalidateQueries({ queryKey: ["branch-voices", branchId] });
      toast.success("Voice updated");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not update the voice")),
  });
  const setLanguage = useMutation({
    mutationFn: (language) => setBranchVoice(branchId, null, language),
    onSuccess: (updated) => {
      qc.setQueryData(["branch-settings", branchId], updated);
      qc.invalidateQueries({ queryKey: ["branch-voices", branchId] });
      toast.success("Call language updated");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not update the call language")),
  });
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("consent_confirmed", String(consent));
      form.append("file", file, file.name);
      return createVoiceClone(branchId, form);
    },
    onSuccess: (created) => {
      // Cloning is asynchronous. Keep the returned row visible immediately so
      // an accepted upload never appears to vanish while the list refetches.
      qc.setQueryData(["voice-clones", branchId], (current) => ({
        ...(current ?? { voices: [], clinic_count: 0, sync_warning: null }),
        voices: [created, ...(current?.voices ?? []).filter((voice) => voice.id !== created.id)],
        clinic_count: 1,
      }));
      setName(""); setFile(null); setConsent(false);
      toast.success("Voice uploaded. Soniox is preparing it now.");
    },
    onError: (error) => {
      toast.error(errorMessage(error, "Could not create this voice"));
      // The server may have recorded a failed upload with a useful recovery
      // message. Refresh only on failure; a success already seeded the cache.
      qc.invalidateQueries({ queryKey: ["voice-clones", branchId] });
    },
  });

  const attach = useMutation({
    mutationFn: () => importVoiceClone(branchId, {
      name: name.trim(),
      voice_id: voiceId.trim(),
      consent_confirmed: consent,
    }),
    onSuccess: (created) => {
      qc.setQueryData(["voice-clones", branchId], (current) => ({
        ...(current ?? { voices: [], clinic_count: 0, sync_warning: null }),
        voices: [created, ...(current?.voices ?? []).filter((voice) => voice.id !== created.id)],
        clinic_count: 1,
      }));
      setName(""); setVoiceId(""); setConsent(false);
      toast.success("Soniox voice added to this clinic");
    },
    onError: (error) => {
      toast.error(errorMessage(error, "Could not add this Soniox voice"));
      qc.invalidateQueries({ queryKey: ["voice-clones", branchId] });
    },
  });

  const stopRecording = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  };
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      const preferred = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
      streamRef.current = stream; recorderRef.current = recorder; chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        clearInterval(timerRef.current);
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        setFile(new File([blob], `clinic-voice-${Date.now()}.${type.includes("ogg") ? "ogg" : "webm"}`, { type }));
        setRecording(false);
        stream.getTracks().forEach((track) => track.stop());
      };
      setSeconds(0); setRecording(true); recorder.start(250);
      const started = Date.now();
      timerRef.current = setInterval(() => {
        const elapsed = Math.min(MAX_SECONDS, Math.ceil((Date.now() - started) / 1000));
        setSeconds(elapsed);
        if (elapsed >= MAX_SECONDS) stopRecording();
      }, 250);
    } catch {
      toast.error("Microphone access is required to record a voice sample");
    }
  };
  const chooseFile = (candidate) => {
    if (!candidate) return;
    if (candidate.size > MAX_BYTES) { toast.error("Reference audio must be 10 MB or smaller"); return; }
    // Metadata parsing differs between browsers and phone recordings. It is a
    // helpful duration check, never a reason to silently discard a valid file.
    setFile(candidate);
    const url = URL.createObjectURL(candidate);
    const audio = new Audio(url);
    audio.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      if (Number.isFinite(audio.duration) && audio.duration > MAX_SECONDS + 0.25) {
        setFile(null);
        toast.error("Reference audio must be 20 seconds or shorter");
      }
    };
    audio.onerror = () => { URL.revokeObjectURL(url); };
  };
  const playClone = async (voice) => {
    if (playingId === voice.id) { audioRef.current?.pause(); setPlayingId(null); return; }
    try {
      audioRef.current?.pause();
      const blob = await previewVoiceClone(branchId, voice.id);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url); audioRef.current = audio; setPlayingId(voice.id);
      audio.onended = () => { URL.revokeObjectURL(url); setPlayingId(null); };
      audio.onerror = () => { URL.revokeObjectURL(url); setPlayingId(null); toast.error("Preview could not be played"); };
      await audio.play();
    } catch (error) {
      setPlayingId(null); toast.error(errorMessage(error, "Preview could not be generated"));
    }
  };
  const readyToUpload = Boolean(name.trim() && file && consent && !recording && !upload.isPending);
  const readyToAttach = Boolean(name.trim() && voiceId.trim() && consent && !attach.isPending);
  const catalogVoices = (catalog.data?.voices ?? []).filter((voice) => voice.kind !== "clone");
  const cloneCount = clones.data?.clinic_count ?? clones.data?.voices?.length ?? 0;
  const hasCustomVoice = cloneCount >= MAX_CUSTOM_VOICES;
  const languageOptions = branch.data?.allowed_languages?.length
    ? branch.data.allowed_languages.map((language) => ({ code: language.code, label: `${language.native_name} (${language.name})` }))
    : LANGUAGES;

  return (
    <div className="voices-page">
      <PageHeader eyebrow="Voice studio" title="A voice patients remember"
        sub="Choose a Soniox studio voice or create a consented clinic voice from one clean recording. The selected voice applies from the next call." />

      <section className="voice-configuration" aria-label="Call language and voice settings">
        <div>
          <p className="voice-kicker">Call configuration</p>
          <h2>Language and voice, in one place</h2>
          <p>The language applies on the next call. Your selected studio or custom voice remains active.</p>
        </div>
        <label className="voice-language-field">
          <span>Agent language</span>
          <select className="field" value={branch.data?.language ?? "te"}
            disabled={branch.isLoading || setLanguage.isPending}
            onChange={(event) => setLanguage.mutate(event.target.value)}>
            {languageOptions.map((language) => <option key={language.code} value={language.code}>{language.label}</option>)}
          </select>
        </label>
      </section>

      <section className="voice-studio-grid">
        <article className="voice-recorder-panel">
          <div className="voice-section-heading"><span>01</span><div><h2>Capture the voice</h2><p>One speaker, a quiet room, and a steady natural tone.</p></div></div>
          <div className={`recording-stage ${recording ? "is-recording" : ""}`}>
            <div className="recording-orbit"><Microphone size={30} weight="duotone" /><span /></div>
            <VoiceBars active={recording} />
            <strong>{recording ? `${seconds}s / ${MAX_SECONDS}s` : file ? "Sample ready" : "Up to 20 seconds"}</strong>
            <p>{recording ? "Speak naturally. Keep the same distance from the microphone." : file ? file.name : "Read a normal clinic greeting in the voice patients should hear."}</p>
            <div className="recording-actions">
              <button type="button" className={recording ? "record-stop" : "record-start"} onClick={recording ? stopRecording : startRecording}>
                {recording ? <Stop size={17} weight="fill" /> : <Microphone size={17} weight="fill" />}
                {recording ? "Stop recording" : "Record now"}
              </button>
              <label className="upload-audio"><UploadSimple size={17} /><span>Upload audio</span><input type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm" onChange={(event) => { chooseFile(event.target.files?.[0]); event.target.value = ""; }} /></label>
            </div>
            {previewUrl && <div className="source-preview"><audio className="source-audio" controls src={previewUrl}>Your browser cannot play this recording.</audio><button type="button" className="source-remove" onClick={() => setFile(null)} aria-label="Remove selected recording" title="Remove recording"><Trash size={16} /></button></div>}
          </div>
        </article>

        <article className="voice-create-panel">
          <div className="voice-section-heading"><span>02</span><div><h2>Add your custom voice</h2><p>Create one from the sample, or connect a voice already in your Soniox account.</p></div></div>
          <label className="voice-name-field"><span>Voice name</span><input className="field" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Dr Lakshmi's clinic voice" /></label>
          <label className="voice-consent">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span><ShieldCheck size={22} weight="duotone" /><span><strong>I have the speaker’s explicit permission</strong><small>I confirm the speaker owns this voice or authorised this clinic to create and use its AI clone.</small></span></span>
          </label>
          <div className="voice-safety-note"><FileAudio size={20} /><p><strong>Create from the sample</strong><span>Maximum 20 seconds and 10 MB. Avoid music, other speakers, echo, mouth clicks, and background noise.</span></p></div>
          {hasCustomVoice && <p className="voice-limit-note">This clinic already has its one custom voice. Remove it below before adding a replacement.</p>}
          <button type="button" className="btn-primary voice-create-button" disabled={!readyToUpload || hasCustomVoice} onClick={() => upload.mutate()}>
            <Waveform size={18} weight="bold" />{upload.isPending ? "Creating voice…" : "Create Soniox voice"}
          </button>

          <div className="voice-existing-divider"><span>Already created in Soniox?</span></div>
          <div className="voice-id-field">
            <label htmlFor="soniox-voice-id">Soniox voice ID</label>
            <input id="soniox-voice-id" className="field" maxLength={64} value={voiceId} onChange={(event) => setVoiceId(event.target.value)} placeholder="Paste the voice ID from Soniox" autoComplete="off" spellCheck="false" aria-describedby="soniox-voice-id-help" />
            <small id="soniox-voice-id-help">We verify this ID against the connected Soniox account before saving it.</small>
          </div>
          <button type="button" className="btn-secondary voice-attach-button" disabled={!readyToAttach || hasCustomVoice} onClick={() => attach.mutate()}>
            <LinkSimple size={18} weight="bold" />{attach.isPending ? "Verifying voice…" : "Add existing voice"}
          </button>
        </article>
      </section>

      <section className="voice-library">
        <div className="voice-library-head"><div><span>03</span><h2>Your clinic voice</h2><p>Preparation normally finishes within seconds. Only a ready voice can be used on calls.</p></div><span>{cloneCount}/{MAX_CUSTOM_VOICES} custom voice</span></div>
        {clones.data?.sync_warning && <p className="voice-sync-warning">{clones.data.sync_warning}. Showing the last known state.</p>}
        {clones.isLoading ? <div className="clone-loading"><i /><i /></div> : clones.data?.voices?.length ? (
          <div className="clone-list">{clones.data.voices.map((voice) => <CloneCard key={voice.id} voice={voice} branchId={branchId} playing={playingId === voice.id} onPlay={playClone} />)}</div>
        ) : (
          <div className="clone-empty"><Waveform size={29} weight="duotone" /><h3>No custom voices yet</h3><p>Record a clean sample above. Your first clone will appear here while Soniox prepares it.</p></div>
        )}
      </section>

      <section className="catalog-voice-row">
        <div><span>Soniox studio collection</span><h2>Prefer a ready-made voice?</h2><p>All studio and cloned voices preserve their identity when patients switch languages.</p></div>
        <label><span>Active studio voice</span><select className="field" value={catalogVoices.some((voice) => voice.voice_id === branch.data?.tts_voice) ? branch.data.tts_voice : ""}
          disabled={catalog.isLoading || setCatalogVoice.isPending} onChange={(event) => event.target.value && setCatalogVoice.mutate(event.target.value)}>
          <option value="" disabled>{branch.data?.tts_voice && !catalogVoices.some((voice) => voice.voice_id === branch.data.tts_voice) ? "Custom voice active" : "Choose a studio voice"}</option>
          {catalogVoices.map((voice) => <option key={voice.voice_id} value={voice.voice_id}>{voice.display_name}{voice.gender ? ` · ${voice.gender}` : ""}</option>)}
        </select></label>
      </section>
    </div>
  );
}
