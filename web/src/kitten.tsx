import { useEffect, useRef } from 'react';
import readingKitten from './assets/kat-reading.svg?raw';

/** This fixed, bundled artwork is not user-supplied markup. Its styles live in style.css for CSP. */
export function ReadingKitten() {
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

  return <span className="reading-kitten" aria-hidden="true" ref={container}
    dangerouslySetInnerHTML={{ __html: readingKitten }} />;
}
