import { useState } from 'react';
import './thinking.css';

const artworks = ['lunar-talisman', 'celestial-sigil', 'moonlit-cauldron'] as const;
const choices = new Map<string, typeof artworks[number]>();

// The archive's turn ID identifies one acknowledged wait across view remounts.
// Bound the small session-only cache; no timer, persisted preference or cycling.
export function ThinkingIndicator({ waitId }: { waitId: string }) {
  const [artwork] = useState(() => {
    const existing = choices.get(waitId);
    if (existing) return existing;
    const chosen = artworks[Math.floor(Math.random() * artworks.length)];
    choices.set(waitId, chosen);
    if (choices.size > 64) choices.delete(choices.keys().next().value!);
    return chosen;
  });
  return <div className="thinking-wait" role="status" aria-label="Thinking" data-artwork={artwork}>
    {artwork === 'lunar-talisman' && <svg className="thinking-art" viewBox="0 0 120 120" aria-hidden="true">
      <defs><linearGradient id="thinking-lunar-gold" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="var(--thinking-gold-light)"/><stop offset=".5" stopColor="var(--thinking-star)"/><stop offset="1" stopColor="var(--accent)"/>
      </linearGradient></defs>
      <circle className="thinking-ring" cx="60" cy="60" r="51"/><circle className="thinking-ring thinking-dash" cx="60" cy="60" r="46"/>
      <circle className="thinking-ring" cx="60" cy="60" r="36"/>
      <path className="thinking-fine" d="M60 4v9M60 107v9M4 60h9M107 60h9M20 20l6 6M94 94l6 6M20 100l6-6M94 26l6-6"/>
      <g className="thinking-crescent"><path className="thinking-moon-fill" d="M69 30C48 27 30 42 33 61c2 21 26 33 44 21-20-3-30-27-8-52Z"/>
        <circle className="thinking-crater" cx="44" cy="56" r="4"/><circle className="thinking-crater" cx="48" cy="73" r="2.4"/>
        <path className="thinking-pot-detail" d="M44 42c-12 15-5 33 10 39"/></g>
      <g className="thinking-orbit"><path className="thinking-gold" d="m60 2 2.1 5.9L68 10l-5.9 2.1L60 18l-2.1-5.9L52 10l5.9-2.1Z"/>
        <circle className="thinking-gold" cx="60" cy="111" r="1.7"/></g>
      <g className="thinking-orbit thinking-reverse"><circle className="thinking-gold" cx="60" cy="24" r="2"/>
        <path className="thinking-fine" d="M60 20v8M56 24h8"/></g>
      <g><path className="thinking-dust" d="m78 39 1.5 4.5L84 45l-4.5 1.5L78 51l-1.5-4.5L72 45l4.5-1.5Z"/>
        <circle className="thinking-dust" cx="83" cy="66" r="1.3"/><circle className="thinking-dust" cx="67" cy="69" r="1"/>
        <circle className="thinking-dust" cx="25" cy="35" r="1.2"/><circle className="thinking-dust" cx="94" cy="87" r="1.5"/></g>
      <text className="thinking-zodiac" x="12" y="66">☿︎</text><text className="thinking-zodiac" x="99" y="66">♀︎</text>
    </svg>}
    {artwork === 'celestial-sigil' && <svg className="thinking-art" viewBox="0 0 120 120" aria-hidden="true">
      <circle className="thinking-ring" cx="60" cy="60" r="49"/><circle className="thinking-ring thinking-dash" cx="60" cy="60" r="44"/>
      <ellipse className="thinking-ring" cx="60" cy="60" rx="54" ry="23" transform="rotate(-28 60 60)"/>
      <g className="thinking-sigil"><path className="thinking-fine" opacity=".35" d="m60 22 33 57H27Zm0 76L27 41h66ZM60 22v76M27 41l66 38M93 41 27 79"/>
        <path className="thinking-thread" d="m60 22 33 57H27L60 22 93 41 60 98 27 41h66"/>
        <circle className="thinking-node" cx="60" cy="22" r="2.7"/><circle className="thinking-node" cx="93" cy="41" r="2.7"/>
        <circle className="thinking-node" cx="93" cy="79" r="2.7"/><circle className="thinking-node" cx="60" cy="98" r="2.7"/>
        <circle className="thinking-node" cx="27" cy="79" r="2.7"/><circle className="thinking-node" cx="27" cy="41" r="2.7"/>
        <path className="thinking-core" d="m60 47 3.2 9.8L73 60l-9.8 3.2L60 73l-3.2-9.8L47 60l9.8-3.2Z"/>
        <circle className="thinking-ring" cx="60" cy="60" r="16"/></g>
      <g className="thinking-orbit thinking-reverse"><path className="thinking-gold" d="m60 5 1.4 4.6L66 11l-4.6 1.4L60 17l-1.4-4.6L54 11l4.6-1.4Z"/>
        <circle className="thinking-gold" cx="60" cy="109" r="1.8"/></g>
      <g><circle className="thinking-dust" cx="15" cy="77" r="1.2"/><circle className="thinking-dust" cx="105" cy="42" r="1.4"/>
        <path className="thinking-dust" d="m100 90 1.2 3.8L105 95l-3.8 1.2L100 100l-1.2-3.8L95 95l3.8-1.2Z"/></g>
    </svg>}
    {artwork === 'moonlit-cauldron' && <svg className="thinking-art" viewBox="0 0 120 120" aria-hidden="true">
      <defs><linearGradient id="thinking-pot-metal" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="var(--thinking-metal)"/><stop offset=".55" stopColor="var(--thinking-deep)"/>
        <stop offset="1" stopColor="var(--thinking-metal)"/>
      </linearGradient></defs>
      <path className="thinking-ring" strokeDasharray="1 5" d="M18 70a44 44 0 1 1 84 0"/>
      <path className="thinking-ring" d="M23 39a42 42 0 0 1 74 0"/>
      <path className="thinking-handle" d="M34 64C9 52 14 83 34 78M86 64c25-12 20 19 0 14"/>
      <path className="thinking-bowl" d="M31 56c-10 24 0 43 29 43s39-19 29-43Z"/>
      <ellipse className="thinking-bowl" cx="60" cy="56" rx="30" ry="8"/>
      <ellipse className="thinking-liquid" cx="60" cy="55" rx="24" ry="4.4"/>
      <ellipse className="thinking-ripple" cx="60" cy="55" rx="20" ry="2.9"/>
      <ellipse className="thinking-ripple second" cx="60" cy="55" rx="12" ry="2.2"/>
      <path className="thinking-pot-detail" d="M34 65c5 4 47 4 52 0M37 86c13 10 34 9 46 0M42 95l-4 10h7M78 95l4 10h-7"/>
      <path fill="var(--thinking-gold-light)" stroke="var(--thinking-star)" strokeWidth=".3" d="M64 71a9 9 0 1 0 4 16A10 10 0 0 1 64 71Z"/>
      <path className="thinking-vapour" d="M51 48c-19-16 25-16 4-33"/>
      <path className="thinking-vapour second" d="M66 47c23-16-18-15 5-34"/>
      <g className="thinking-ember"><path fill="var(--thinking-gold-light)" d="m41 25 1.2 4.8L47 31l-4.8 1.2L41 37l-1.2-4.8L35 31l4.8-1.2Z"/></g>
      <circle className="thinking-ember second" cx="77" cy="31" r="2"/>
      <path className="thinking-ember third" d="m60 15 1.2 3.8L65 20l-3.8 1.2L60 25l-1.2-3.8L55 20l3.8-1.2Z"/>
      <g><circle className="thinking-dust" cx="24" cy="42" r="1.2"/><circle className="thinking-dust" cx="94" cy="27" r="1.4"/>
        <circle className="thinking-dust" cx="87" cy="15" r="1"/><path className="thinking-dust" d="m31 12 1 3 3 1-3 1-1 3-1-3-3-1 3-1Z"/></g>
    </svg>}
    <span className="thinking-label" aria-hidden="true">Thinking</span>
  </div>;
}
