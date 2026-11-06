import { useEffect, useRef } from 'react';
import crescentKitten from './assets/kat-crescent.svg?raw';
import readingKitten from './assets/kat-reading.svg?raw';

// Both SVGs are fixed bundled artwork. The source crescent's embedded style is
// for standalone exports; inline artwork uses style.css under the strict CSP.
const crescentInline = crescentKitten.replace(/<style>[\s\S]*?<\/style>/, '');

function KittenArt({ variant }: { variant: 'brand' | 'reading' }) {
  const container = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const element = container.current;
    const illustration = element?.querySelector('svg');
    if (!element || !illustration) return;

    let inView = false;
    const update = () => illustration.setAttribute('data-motion',
      inView && document.visibilityState === 'visible' ? 'on' : 'off');
    const observer = new IntersectionObserver(entries => {
      inView = entries[0]?.isIntersecting ?? false;
      update();
    });
    observer.observe(element);
    document.addEventListener('visibilitychange', update);
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', update);
      illustration.setAttribute('data-motion', 'off');
    };
  }, []);

  return <span className={`kitten-art ${variant === 'brand' ? 'brand-kitten' : 'reading-kitten'}`}
    aria-hidden="true" ref={container}
    dangerouslySetInnerHTML={{ __html: variant === 'brand' ? crescentInline : readingKitten }} />;
}

export function BrandKitten() {
  return <KittenArt variant="brand" />;
}

export function ReadingKitten() {
  return <KittenArt variant="reading" />;
}
