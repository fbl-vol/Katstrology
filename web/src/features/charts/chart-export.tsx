import { useRef, useState, type RefObject } from 'react';
import { embeddedGlyphFontsStyle } from './chart-symbols';

const paletteNames = ['paper', 'frame', 'ring', 'ink', 'muted', 'angle', 'cusp', 'glyph', 'leader',
  'sky', 'natal', 'aspect-gold', 'aspect-warm', 'aspect-cool'] as const;
const printPalette: Record<(typeof paletteNames)[number], string> = {
  paper: '#ffffff', frame: '#77877d', ring: '#8a9a90', ink: '#1b3027', muted: '#47574e',
  angle: '#203c2d', cusp: '#87998d', glyph: '#193126', leader: '#52675b',
  sky: '#176257', natal: '#95602d', 'aspect-gold': '#88621e',
  'aspect-warm': '#a14b38', 'aspect-cool': '#276b61',
};
const svgNamespace = 'http://www.w3.org/2000/svg';

function wheelMarkup(svg: SVGSVGElement, mode: 'existing' | 'screen' | 'print', provenance: object) {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute('xmlns', svgNamespace);
  // Exploration is transient UI, not saved chart evidence or export geometry.
  copy.querySelectorAll('[data-exploration-overlay]').forEach(node => node.remove());
  copy.classList.remove('exploring');
  copy.querySelector('[data-wheel-caption]')?.setAttribute('opacity', '1');
  copy.setAttribute('role', 'img');
  const fontStyles = document.createElementNS(svgNamespace, 'style');
  fontStyles.textContent = embeddedGlyphFontsStyle;
  copy.insertBefore(fontStyles, copy.firstChild);
  if (mode !== 'existing') {
    const computed = getComputedStyle(svg);
    for (const name of paletteNames) {
      const value = mode === 'print' ? printPalette[name] : computed.getPropertyValue(`--wheel-${name}`).trim();
      if (value) copy.style.setProperty(`--wheel-${name}`, value);
    }
  }
  if (mode !== 'existing') {
    copy.setAttribute('width', '480'); copy.setAttribute('height', '480');
  }
  const metadata = document.createElementNS(svgNamespace, 'metadata');
  metadata.setAttribute('id', 'kat-chart-provenance');
  metadata.textContent = JSON.stringify(provenance);
  copy.append(metadata);
  return new XMLSerializer().serializeToString(copy);
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function rasterize(markup: string): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = image.width * 2; canvas.height = image.height * 2;
      const context = canvas.getContext('2d');
      if (!context) { reject(new Error('Canvas unavailable')); return; }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG unavailable')), 'image/png');
    };
    image.onerror = () => reject(new Error('SVG could not be rasterized'));
    // The local CSP permits data images, not remote resources or blob images.
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  });
}

export function WheelExportActions({ svgRef, stem, provenance }: {
  svgRef: RefObject<SVGSVGElement | null>; stem: string; provenance: object;
}) {
  const [error, setError] = useState('');
  const [preparing, setPreparing] = useState(false);
  const disclosure = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const choices = useRef<HTMLDivElement>(null);

  function close() {
    if (disclosure.current) disclosure.current.open = false;
    trigger.current?.focus({ preventScroll: true });
  }
  async function download(format: 'svg' | 'png' | 'print') {
    if (preparing || !svgRef.current) return;
    setError(''); setPreparing(true); close();
    try {
      // Capture the exact selected result before asynchronous PNG preparation.
      const markup = wheelMarkup(svgRef.current, format === 'png' ? 'screen' : format === 'print' ? 'print' : 'existing', provenance);
      if (format === 'png') save(await rasterize(markup), `${stem}.png`);
      else save(new Blob([markup], { type: 'image/svg+xml' }), `${stem}${format === 'print' ? '-print' : ''}.svg`);
    } catch {
      setError(format === 'png' ? 'PNG could not be prepared in this browser. The standalone SVG is still available.' :
        'SVG could not be prepared in this browser. Your chart is unchanged; try another format.');
    } finally { setPreparing(false); }
  }
  return <><details className="wheel-export-actions" ref={disclosure}
    onToggle={event => { if (event.currentTarget.open) choices.current?.scrollIntoView({ block: 'nearest', behavior: 'instant' }); }}
    onKeyDown={event => { if (event.key === 'Escape' && disclosure.current?.open) { event.preventDefault(); event.stopPropagation(); close(); } }}>
    <summary ref={trigger} aria-disabled={preparing} onClick={event => { if (preparing) event.preventDefault(); }}>Download chart</summary>
    <div ref={choices} className="wheel-export-menu" role="group" aria-label="Chart download formats">
      <button type="button" disabled={preparing} onClick={() => void download('png')} aria-label="Download PNG wheel">
        PNG image<small>Uses your current reading palette</small></button>
      <button type="button" disabled={preparing} onClick={() => void download('svg')} aria-label="Download safe SVG wheel">
        SVG image<small>Scalable image with its original light palette</small></button>
      <button type="button" disabled={preparing} onClick={() => void download('print')} aria-label="Download print-ready SVG">
        Print-ready SVG<small>White background for printing</small></button>
    </div>
  </details>
  {preparing && <p role="status" className="wheel-export-note">Preparing chart…</p>}
  {error && <p role="alert" className="error">{error}</p>}</>;
}
