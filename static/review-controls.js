(function (root) {
  'use strict';

  function selectionInRectangle(cards, rectangle, previous, additive) {
    const result = new Set(additive ? previous : []);
    for (const card of cards) {
      const r = card.rect;
      if (r.left < rectangle.right && r.right > rectangle.left &&
          r.top < rectangle.bottom && r.bottom > rectangle.top) {
        result.add(card.id);
      }
    }
    return result;
  }

  function shouldRefreshResults({pending, selectedCount, revealed, dragging, running, elapsed}) {
    return pending && !selectedCount && !revealed && !dragging && (!running || elapsed >= 6000);
  }

  function pageInfo(total, pageSize, requestedPage) {
    const pages = Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
    const page = Math.max(1, Math.min(pages, requestedPage));
    return {page, pages, offset: (page - 1) * pageSize};
  }

  function installMarquee(container, options) {
    let gesture = null;
    function finish(cancelled) {
      if (!gesture) return;
      const previous = gesture;
      gesture = null;
      if (cancelled && previous.active) options.setSelected(new Set(previous.previous));
      previous.overlay?.remove();
      document.body.classList.remove('marquee-active');
      if (container.hasPointerCapture?.(previous.pointerId)) {
        container.releasePointerCapture(previous.pointerId);
      }
    }
    function draw() {
      const x = gesture.clientX + window.scrollX;
      const y = gesture.clientY + window.scrollY;
      const rectangle = {
        left: Math.min(gesture.startX, x), right: Math.max(gesture.startX, x),
        top: Math.min(gesture.startY, y), bottom: Math.max(gesture.startY, y),
      };
      Object.assign(gesture.overlay.style, {
        left: `${rectangle.left}px`, top: `${rectangle.top}px`,
        width: `${rectangle.right - rectangle.left}px`,
        height: `${rectangle.bottom - rectangle.top}px`,
      });
      const cards = [...container.querySelectorAll('.card')].filter(card => card.querySelector('input[data-id]')).map(card => {
        const r = card.getBoundingClientRect();
        return {id: card.dataset.id, rect: {
          left: r.left + window.scrollX, right: r.right + window.scrollX,
          top: r.top + window.scrollY, bottom: r.bottom + window.scrollY,
        }};
      });
      options.setSelected(selectionInRectangle(cards, rectangle, gesture.previous, gesture.additive));
    }
    container.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.pointerType !== 'mouse' || !options.canSelect() ||
          event.target.closest('button,input,select,a,label')) return;
      finish(true);
      gesture = {
        pointerId: event.pointerId, startX: event.pageX, startY: event.pageY,
        clientX: event.clientX, clientY: event.clientY,
        initialClientX: event.clientX, initialClientY: event.clientY,
        previous: new Set(options.getSelected()), additive: event.ctrlKey || event.metaKey,
        active: false, overlay: null,
      };
      event.preventDefault();
    });
    window.addEventListener('pointermove', event => {
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      gesture.clientX = event.clientX;
      gesture.clientY = event.clientY;
      if (!gesture.active) {
        if (Math.hypot(event.clientX - gesture.initialClientX, event.clientY - gesture.initialClientY) < 5) return;
        gesture.active = true;
        gesture.overlay = document.createElement('div');
        gesture.overlay.className = 'selection-marquee';
        gesture.overlay.setAttribute('aria-hidden', 'true');
        document.body.append(gesture.overlay);
        document.body.classList.add('marquee-active');
        container.setPointerCapture(event.pointerId);
      }
      draw();
    });
    window.addEventListener('pointerup', event => {
      if (gesture && event.pointerId === gesture.pointerId) finish(false);
    });
    window.addEventListener('pointercancel', () => finish(true));
    window.addEventListener('blur', () => finish(true));
    window.addEventListener('scroll', () => { if (gesture?.active) draw(); });
    window.addEventListener('keydown', event => {
      if (event.key === 'Escape' && gesture) { finish(true); event.preventDefault(); }
    });
    container.addEventListener('lostpointercapture', () => finish(false));
    return {cancel: () => finish(true), isActive: () => !!gesture};
  }

  const api = {selectionInRectangle, shouldRefreshResults, pageInfo, installMarquee};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ReviewControls = api;
})(typeof window !== 'undefined' ? window : globalThis);
