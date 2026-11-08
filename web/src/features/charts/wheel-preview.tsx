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
      const topEdge = (viewport?.offsetTop ?? 0) + 12;
      const bottomEdge = topEdge + (viewport?.height ?? innerHeight) - 24;
      const height = preview.offsetHeight;
      container.style.height = `${height}px`;
      const naturalTop = container.getBoundingClientRect().top;
      const visible = bounds.bottom > topEdge && bounds.top < bottomEdge;
      if (!visible || naturalTop + height <= bottomEdge || height > bottomEdge - topEdge) {
        preview.style.position = 'static'; preview.style.width = '100%';
        return;
      }
      const matrix = svg!.getScreenCTM();
      if (!matrix) return;
      const target = new DOMPoint(point.location.x, point.location.y).matrixTransform(matrix);
      let top = bottomEdge - height;
      if (target.y >= top - 16 && target.y <= top + height + 16) {
        const above = target.y - height - 24;
        top = above >= topEdge ? above : target.y + 24;
        // Enlarged text can leave no unobscured space on either side. Keep the
        // complete preview in document flow rather than covering its target.
        if (top + height > bottomEdge) {
          preview.style.position = 'static'; preview.style.width = '100%';
          return;
        }
      }
      preview.style.position = 'fixed';
      preview.style.top = `${top}px`;
      preview.style.left = `${container.getBoundingClientRect().left}px`;
      preview.style.width = `${container.clientWidth}px`;
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
