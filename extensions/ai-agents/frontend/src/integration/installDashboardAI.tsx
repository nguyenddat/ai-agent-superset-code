import { createRoot, Root } from 'react-dom/client';
import { AIChatSidebar } from '../features/chat/components/AIChatSidebar';

/** DOM adapter for the Superset 6.1 dashboard header, for viewers and editors. */
export function installDashboardAI(): () => void {
  let root: Root | undefined;
  let mountNode: HTMLSpanElement | undefined;
  let currentKey = '';
  let frame = 0;

  const clear = () => {
    root?.unmount();
    mountNode?.remove();
    root = undefined;
    mountNode = undefined;
    currentKey = '';
  };

  const mount = () => {
    frame = 0;
    const dashboard = location.pathname.match(/^\/superset\/dashboard\/([^/]+)/)?.[1];
    const menu = document.querySelector<HTMLButtonElement>('button[data-test="actions-trigger"]');
    if (!dashboard || !menu) {
      if (root) clear();
      return;
    }
    const anchor = menu.parentElement?.parentElement?.classList.contains("right-button-panel") ? menu.parentElement : menu;
    const title = document.querySelector<HTMLInputElement>('input[aria-label="Dashboard title"]')?.value;
    const key = `${dashboard}:${title || ''}`;
    if (mountNode?.isConnected && currentKey === key && mountNode.nextElementSibling === anchor) return;
    clear();
    mountNode = document.createElement('span');
    mountNode.setAttribute('data-ai-dashboard-assistant', 'true');
    anchor.before(mountNode);
    currentKey = key;
    root = createRoot(mountNode);
    root.render(<AIChatSidebar key={dashboard} dashboardId={decodeURIComponent(dashboard)} dashboardTitle={title} />);
  };

  const schedule = () => { if (!frame) frame = requestAnimationFrame(mount); };
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener('popstate', schedule);
  mount();
  return () => {
    observer.disconnect();
    window.removeEventListener('popstate', schedule);
    cancelAnimationFrame(frame);
    clear();
  };
}
