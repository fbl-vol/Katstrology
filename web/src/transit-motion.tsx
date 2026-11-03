import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { bodyGlyph, bodyLabel } from './chart-symbols';
import { point, signs } from './chart-geometry';
import type { Chart } from './natal';

type Motion = { status: string; start_utc: string; end_utc: string; step_seconds: number;
  chart_id: string; bodies: string[]; longitudes: number[][]; qualification: string };
const DURATION_MS = 20_000;

function labelTracks(bodies: { id: string; longitude_degrees: number }[]) {
  const sorted = [...bodies].sort((a, b) => a.longitude_degrees - b.longitude_degrees);
  const tracks = new Map<string, number>();
  let previous = sorted.at(-1)!.longitude_degrees - 360;
  let cluster = 0;
  for (const body of sorted) {
    cluster = body.longitude_degrees - previous < 12 ? cluster + 1 : 0;
    tracks.set(body.id, cluster % 3 * 18);
    previous = body.longitude_degrees;
  }
  return tracks;
}

function skyCallouts(bodies: { id: string; longitude_degrees: number }[]) {
  const marks = new Map<string, { x: number; y: number }>();
  for (const body of [...bodies].sort((a, b) => a.longitude_degrees - b.longitude_degrees)) {
    // Keep the sampled/interpolated longitude on the 156px ring; move only the linked glyph.
    for (let spread = 0; spread <= 180 && !marks.has(body.id); spread += 10) {
      for (const offset of spread ? [-spread, spread] : [0]) {
        for (const radius of [140, 168, 196]) {
          const spot = point(body.longitude_degrees + offset, 0, radius);
          if ([...marks.values()].every(mark => Math.hypot(spot.x - mark.x, spot.y - mark.y) >= 24)) {
            marks.set(body.id, spot);
            break;
          }
        }
        if (marks.has(body.id)) break;
      }
    }
  }
  return marks;
}

function MotionWheel({ chart, motion, frame }: { chart: Chart; motion: Motion; frame: number }) {
  const natal = chart.result.natal!;
  const index = Math.min(Math.floor(frame), motion.longitudes.length - 2);
  const fraction = frame - index;
  const positions = motion.bodies.map((body, i) => {
    const from = motion.longitudes[index][i], to = motion.longitudes[index + 1][i];
    return { id: body, longitude_degrees: (from + ((to - from + 540) % 360 - 180) * fraction + 360) % 360 };
  });
  const natalTracks = labelTracks(natal.positions);
  const skyMarks = skyCallouts(positions);
  const timestamp = new Date(Date.parse(motion.start_utc) + frame * motion.step_seconds * 1000);
  const time = timestamp.toLocaleString('en-GB', { timeZone: 'UTC', day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit' });
  const id = `motion-${chart.id}`;
  return <div className="motion-view"><p><strong>{time} UTC</strong> · the chosen dates play over 20 seconds. Natal positions stay fixed.</p>
    <div className="natal-wheel-scroll"><svg className="natal-wheel" viewBox="0 0 480 480" role="img"
      aria-labelledby={`${id}-title ${id}-desc`}>
      <title id={`${id}-title`}>Transiting planets around the fixed natal chart at {time} UTC</title>
      <desc id={`${id}-desc`}>{motion.qualification} Outer glyphs are transiting planets; their lines lead to the shown longitude on the middle ring. Glyphs may shift to avoid overlaps. Inner marks are natal positions. Exact positions require the dated transit view.</desc>
      <rect x="1" y="1" width="478" height="478" rx="18" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-frame, #d8dfce)" />
      {[190, 156, 106, 71].map(radius => <circle key={radius} cx="240" cy="240" r={radius}
        fill="none" stroke="var(--wheel-ring, #b9c9b8)" />)}
      {signs.map((sign, i) => { const spot = point(i * 30 + 15, 0, 223);
        return <text key={sign} x={spot.x} y={spot.y} textAnchor="middle" dominantBaseline="middle"
          fontSize="11" fill="var(--wheel-ink, #425e49)">{sign.slice(0, 3)}</text>; })}
      {natal.positions.map(body => { const spot = point(body.longitude_degrees, 0, 78 + (natalTracks.get(body.id) || 0));
        return <g key={`natal-${body.id}`}><circle cx={spot.x} cy={spot.y} r="11" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-natal, #a16134)" />
          <text x={spot.x} y={spot.y} textAnchor="middle" dominantBaseline="middle" fontSize="15"
            fill="var(--wheel-natal, #a16134)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>; })}
      {positions.map(body => { const spot = skyMarks.get(body.id)!;
        const anchor = point(body.longitude_degrees, 0, 156);
        return <g key={`sky-${body.id}`} data-sky-body={body.id}>
          <line x1={anchor.x} y1={anchor.y} x2={spot.x} y2={spot.y}
            stroke="var(--wheel-sky, #245b4e)" strokeWidth="1" />
          <circle cx={spot.x} cy={spot.y} r="11" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-sky, #245b4e)" />
          <text x={spot.x} y={spot.y} textAnchor="middle" dominantBaseline="middle" fontSize="15"
            fill="var(--wheel-sky, #245b4e)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text>
          <circle cx={anchor.x} cy={anchor.y} r="2" fill="var(--wheel-sky, #245b4e)" />
        </g>; })}
    </svg></div><p className="natal-qualification">Outer glyphs: {positions.map(body => bodyLabel(body.id)).join(', ')}. Each line links a glyph to its longitude on the middle ring; glyphs may shift to stay readable. Inner ring: saved natal positions. No aspect events, sky houses or exact intermediate positions are claimed.</p>
  </div>;
}

export function TransitMotion({ chart }: { chart: Chart }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [motion, setMotion] = useState<Motion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [frame, setFrame] = useState(0);
  const [running, setRunning] = useState(false);
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const view = useRef<HTMLDivElement>(null);
  const frameRef = useRef(0);
  const request = useRef(0);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => { setReduced(media.matches); if (media.matches) setRunning(false); };
    media.addEventListener('change', change);
    return () => { media.removeEventListener('change', change); request.current++; };
  }, []);

  useEffect(() => {
    if (!running || !motion || reduced) return;
    let animation = 0;
    let lastPaint = 0;
    const duration = motion.longitudes.length - 1;
    const started = performance.now() - frameRef.current / duration * DURATION_MS;
    const tick = (now: number) => {
      if (now - lastPaint >= 40) {
        lastPaint = now;
        frameRef.current = Math.min(duration, (now - started) / DURATION_MS * duration);
        setFrame(frameRef.current);
      }
      if (frameRef.current >= duration) setRunning(false);
      else animation = requestAnimationFrame(tick);
    };
    const pause = () => { if (document.hidden) setRunning(false); };
    const observer = new IntersectionObserver(entries => {
      if (!entries[0]?.isIntersecting) setRunning(false);
    });
    if (view.current) observer.observe(view.current);
    document.addEventListener('visibilitychange', pause);
    animation = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(animation); observer.disconnect();
      document.removeEventListener('visibilitychange', pause); };
  }, [running, motion, reduced]);

  async function load(event: React.FormEvent) {
    event.preventDefault();
    const version = ++request.current;
    setRunning(false); setMotion(null); setError(''); setBusy(true);
    try {
      const result = await api<Motion>(`charts/${chart.id}/transit-frames?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
      if (version !== request.current) return;
      if (result.status !== 'supported') { setError('This selected natal is no longer current or has no exact birth time. Update the chart before playing transits.'); return; }
      setMotion(result); frameRef.current = 0; setFrame(0);
    } catch {
      if (version === request.current) setError('Transits could not be loaded. Check the UTC dates and try again; no chart was changed.');
    } finally { if (version === request.current) setBusy(false); }
  }

  function changeDate(which: 'from' | 'to', value: string) {
    request.current++;
    setRunning(false); setMotion(null); setError(''); setBusy(false);
    if (which === 'from') setFrom(value); else setTo(value);
  }

  return <details className="transit-motion" onToggle={event => { if (!event.currentTarget.open) setRunning(false); }}>
    <summary>Transits over time</summary>
    <p>Choose 1–7 UTC days to see transiting planets move around the fixed birth chart. Nothing loads or sends a message until you choose Show transits.</p>
    <form onSubmit={event => void load(event)}><label>From (UTC)<input type="date" required min="1900-01-01" max="2099-12-30"
      value={from} onChange={event => changeDate('from', event.target.value)} /></label>
      <label>To (UTC)<input type="date" required min="1900-01-02" max="2099-12-31"
        value={to} onChange={event => changeDate('to', event.target.value)} /></label>
      <button type="submit" disabled={busy}>{busy ? 'Loading transits…' : 'Show transits'}</button></form>
    {error && <p className="error" role="alert">{error}</p>}
    {motion && <div ref={view}>
      <p>Motion between calculated times is approximate. Use Sky at a date for exact positions. This view does not send a message.</p>
      <div className="motion-controls"><button type="button" disabled={reduced} onClick={() => {
        if (frameRef.current >= motion.longitudes.length - 1) { frameRef.current = 0; setFrame(0); }
        setRunning(!running);
      }}>{running ? 'Pause' : frame >= motion.longitudes.length - 1 ? 'Replay' : 'Play'}</button>
      <label>Transit date<input type="range" min="0" max={motion.longitudes.length - 1} step="0.01"
        aria-valuetext={`${new Date(Date.parse(motion.start_utc) + frame * motion.step_seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC`}
        value={frame} onChange={event => { setRunning(false); frameRef.current = Number(event.target.value); setFrame(frameRef.current); }} /></label></div>
      {reduced && <p role="status">Reduced motion is on. Use the time slider to view each moment.</p>}
      <MotionWheel chart={chart} motion={motion} frame={frame} />
    </div>}
  </details>;
}
