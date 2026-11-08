import { useLayoutEffect, useRef, type ReactNode } from 'react';
import type { WheelPoint } from './exploration-targets';

/** A non-modal preview, normally below the wheel. Only lift it when necessary
 * to acknowledge a visible target without scrolling the document. */
export function WheelPreview({ point, children }: { point: WheelPoint; children: ReactNode }) {
  const slot = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const container = slot.current!, preview = card.current!;
    const svg = point.origin.ownerSVGElement;
    if (!svg) return;
    function place() {
      const bounds = svg!.getBoundingClientRect();
      const viewport = window.visualViewport;
      const headerBottom = svg!.closest('.main')?.querySelector('.header')?.getBoundingClientRect().bottom ?? 0;
      const topEdge = Math.max((viewport?.offsetTop ?? 0) + 12, headerBottom + 8);
      const bottomEdge = (viewport?.offsetTop ?? 0) + (viewport?.height ?? innerHeight) - 12;
      const naturalTop = container.getBoundingClientRect().top;
      const visible = bounds.bottom > topEdge && bounds.top < bottomEdge;
      const matrix = svg!.getScreenCTM();
      if (!matrix) return;
      const target = new DOMPoint(point.location.x, point.location.y).matrixTransform(matrix);
      preview.style.width = `${container.clientWidth}px`;
      // At enlarged text sizes, keep the full name and action ahead of optional
      // degree/member context. All that context remains in the complete reader.
      for (const compact of [false, true]) {
        preview.classList.toggle('wheel-preview-compact', compact);
        const height = preview.offsetHeight;
        container.style.height = `${height}px`;
        if (!visible || naturalTop + height <= bottomEdge) {
          preview.style.position = 'static'; return;
        }
        if (height > bottomEdge - topEdge) continue;
        let top = bottomEdge - height;
        if (target.y >= top - 16 && target.y <= top + height + 16) {
          const above = target.y - height - 24;
          top = above >= topEdge ? above : target.y + 24;
          if (top + height > bottomEdge) continue;
        }
        preview.style.position = 'fixed'; preview.style.top = `${top}px`;
        preview.style.left = `${container.getBoundingClientRect().left}px`;
        return;
      }
      // Beyond physically available space, never cover the selected target or
      // clip the name/action. Ordinary document scrolling remains available.
      preview.classList.remove('wheel-preview-compact');
      preview.style.position = 'static'; container.style.height = `${preview.offsetHeight}px`;
    }
    place();
    const observer = new ResizeObserver(place);
    observer.observe(preview); observer.observe(svg);
    window.addEventListener('scroll', place, { passive: true });
    window.addEventListener('resize', place);
    window.visualViewport?.addEventListener('resize', place);
    window.visualViewport?.addEventListener('scroll', place);
    return () => {
      observer.disconnect(); window.removeEventListener('scroll', place); window.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('resize', place); window.visualViewport?.removeEventListener('scroll', place);
    };
  }, [point, children]);
  return <div ref={slot} className="wheel-preview-slot"><div ref={card} className="wheel-preview" role="region" aria-label="Selected chart feature">{children}</div></div>;
}
