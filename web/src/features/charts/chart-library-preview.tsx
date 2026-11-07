import { useId } from 'react';
import { bodyGlyph } from './chart-symbols';
import type { LibraryPreview, PreviewPosition } from './chart-library-data';

const position = (degrees: number, radius: number) => ({
  x: 100 + radius * Math.cos((180 - degrees) * Math.PI / 180),
  y: 100 - radius * Math.sin((180 - degrees) * Math.PI / 180),
});

function Ring({ points, radius, secondary = false }: {
  points: PreviewPosition[]; radius: number; secondary?: boolean;
}) {
  return <g className={secondary ? 'library-preview-secondary' : 'library-preview-primary'}>
    {points.map(body => {
      const p = position(body.longitude_degrees, radius);
      const tick = position(body.longitude_degrees, radius + 7);
      return <g key={body.id}><line x1={p.x} y1={p.y} x2={tick.x} y2={tick.y} />
        <circle cx={p.x} cy={p.y} r="2.3" />
        <text className="library-preview-glyph" x={position(body.longitude_degrees, radius - 10).x}
          y={position(body.longitude_degrees, radius - 10).y} textAnchor="middle" dominantBaseline="middle"
          fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'}>{bodyGlyph(body.id)}</text></g>;
    })}
  </g>;
}

/** A thumbnail of saved coordinates or dated events, never a decorative invented wheel. */
export function ChartLibraryPreview({ preview, label }: { preview: LibraryPreview; label: string }) {
  const title = useId();
  if (preview.kind === 'unavailable' || (preview.kind !== 'timeline' && !preview.positions?.length)) {
    return <div className="library-preview library-preview-empty" role="img" aria-label={`${label}: geometry unavailable`}>
      <span aria-hidden="true">—</span><small>Unavailable</small></div>;
  }
  if (preview.kind === 'timeline') {
    const events = preview.events || [];
    return <div className="library-preview library-preview-timeline" role="img"
      aria-label={`${label}: ${preview.total} saved events${events.length ? `; first dates ${events.map(e => e.date?.slice(0, 10) || 'unrecorded').join(', ')}` : ''}`}>
      <span className="library-event-count">{preview.total}</span><small>saved events</small>
      <ol aria-hidden="true">{events.map((event, i) => <li key={i}><span>{event.date?.slice(0, 10) || 'Undated'}</span></li>)}</ol>
    </div>;
  }
  const points = new Map((preview.positions || []).map(p => [p.id, p.longitude_degrees]));
  return <svg className="library-preview" viewBox="0 0 200 200" role="img" aria-labelledby={title}>
    <title id={title}>{label}: saved {preview.kind === 'comparison' ? 'two-ring comparison' : 'position wheel'} preview. Open for full details.</title>
    <circle className="library-preview-ring" cx="100" cy="100" r="90" />
    <circle className="library-preview-ring" cx="100" cy="100" r="73" />
    {Array.from({ length: 12 }, (_, i) => {
      const a = position(i * 30, 73), b = position(i * 30, 90);
      return <line className="library-preview-ring" key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
    })}
    {(preview.aspects || []).map((edge, i) => {
      const first = points.get(edge.first), second = points.get(edge.second);
      if (first == null || second == null) return null;
      const a = position(first, 47), b = position(second, 47);
      return <line className="library-preview-aspect" key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
    })}
    <Ring points={preview.positions || []} radius={67} />
    {preview.kind === 'comparison' && <><circle className="library-preview-ring" cx="100" cy="100" r="43" />
      <Ring points={preview.other_positions || []} radius={37} secondary /></>}
  </svg>;
}
