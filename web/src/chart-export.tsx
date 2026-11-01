import { useState, type RefObject } from 'react';
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
  function downloadSvg(mode: 'existing' | 'print') {
    if (!svgRef.current) return;
    setError('');
    const markup = wheelMarkup(svgRef.current, mode, provenance);
    save(new Blob([markup], { type: 'image/svg+xml' }), `${stem}${mode === 'print' ? '-print' : ''}.svg`);
  }
  async function downloadPng() {
    if (!svgRef.current) return;
    setError('');
    try {
      const markup = wheelMarkup(svgRef.current, 'screen', provenance);
      save(await rasterize(markup), `${stem}.png`);
    } catch {
      setError('PNG could not be prepared in this browser. The standalone SVG is still available.');
    }
  }
  return <><div className="wheel-export-actions">
    <button type="button" onClick={() => downloadSvg('existing')}>Download safe SVG wheel</button>
    <button type="button" onClick={() => void downloadPng()}>Download PNG wheel</button>
    <button type="button" onClick={() => downloadSvg('print')}>Download print-ready SVG</button>
  </div><p className="wheel-export-note">PNG follows this reading palette; print-ready SVG uses white paper. Original SVG keeps its light fallback.</p>
  {error && <p role="alert" className="error">{error}</p>}</>;
}
