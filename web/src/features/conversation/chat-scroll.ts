import { useCallback, useLayoutEffect, useState } from 'react';

// The document owns chat scrolling. An uncapped editor must leave its sticky dock
// when the dock itself is taller than the available viewport.
export function useGrowingComposer(value?: string) {
  const [textarea, setTextarea] = useState<HTMLTextAreaElement | null>(null);
  const [wrapper, setWrapper] = useState<HTMLDivElement | null>(null);
  const measure = useCallback(() => {
    if (!textarea || !wrapper) return;
    const wasAtBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 80;
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
    textarea.scrollTop = 0;
    wrapper.classList.toggle('composer-in-flow', wrapper.offsetHeight > window.innerHeight - 120);
    if (wasAtBottom && document.activeElement === textarea && textarea.selectionStart === textarea.value.length)
      window.scrollTo(0, document.documentElement.scrollHeight);
  }, [textarea, wrapper]);

  useLayoutEffect(measure, [measure, value]);
  useLayoutEffect(() => {
    if (!wrapper) return;
    const observer = new ResizeObserver(measure);
    observer.observe(wrapper);
    window.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [wrapper, measure]);
  return { input: setTextarea, dock: setWrapper, measure };
}
