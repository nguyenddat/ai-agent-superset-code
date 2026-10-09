import React, { useEffect, useState } from 'react';
import ReactDOM, { createPortal } from 'react-dom';
import { Sparkles } from 'lucide-react';
import { AIChatSidebar } from '../features/chat/components/AIChatSidebar';

const maxDrawerWidth = () => Math.min(960, window.innerWidth * 0.85);
const minDrawerWidth = () => Math.min(360, maxDrawerWidth());

function activeSupersetTheme(): 'light' | 'dark' | 'system' {
  const luminance = (color: string) => {
    const match = color.match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const channels = match[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    if (channels.length < 3 || channels.some(channel => !Number.isFinite(channel))) return null;
    if (channels.length > 3 && channels[3] === 0) return null;
    return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2]);
  };

  const body = getComputedStyle(document.body);
  const backgroundLuminance = luminance(body.backgroundColor);
  if (backgroundLuminance !== null) return backgroundLuminance < 128 ? 'dark' : 'light';

  const textLuminance = luminance(body.color);
  if (textLuminance !== null) return textLuminance > 128 ? 'dark' : 'light';
  return 'system';
}

function DashboardAI({ dashboardId }: { dashboardId: string }) {
  const [open, setOpen] = useState(false);
  const [themeMode, setThemeMode] = useState(activeSupersetTheme);
  const [drawerWidth, setDrawerWidth] = useState(() => Math.min(560, window.innerWidth * 0.62));

  const resizeDrawer = (width: number) => {
    setDrawerWidth(Math.min(Math.max(width, minDrawerWidth()), maxDrawerWidth()));
  };

  const startDrawerResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  useEffect(() => {
    if (!open) return undefined;

    const syncThemeMode = () => {
      // Superset's preference is shared through localStorage across tabs, while
      // its rendered theme is tab-local. Read the active DOM theme so a change
      // in another tab cannot turn this still-dark dashboard light.
      const nextMode = activeSupersetTheme();
      setThemeMode(current => current === nextMode ? current : nextMode);
    };
    const observer = new MutationObserver(syncThemeMode);
    observer.observe(document.body, { attributes: true, childList: true, subtree: true });
    observer.observe(document.head, { childList: true });
    window.addEventListener('storage', syncThemeMode);
    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
    systemTheme.addEventListener('change', syncThemeMode);
    return () => {
      observer.disconnect();
      window.removeEventListener('storage', syncThemeMode);
      systemTheme.removeEventListener('change', syncThemeMode);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="ant-btn ant-btn-default ant-btn-color-primary ant-btn-variant-filled action-button superset-button superset-button-secondary ai-dashboard-trigger"
        aria-label={open ? 'Đóng AI Agent' : 'Mở AI Agent'}
        aria-expanded={open}
        title={open ? 'Đóng AI Agent' : 'Mở AI Agent'}
        onClick={() => setOpen(value => !value)}
      >
        <Sparkles aria-hidden="true" />
        <span>AI Agent</span>
      </button>
      {open && createPortal(
        <div className="ai-chat-drawer-layer" data-theme-mode={themeMode}>
          <button
            type="button"
            className="ai-chat-drawer-backdrop"
            aria-label="Đóng AI Agent"
            onClick={() => setOpen(false)}
          />
          <aside className="ai-chat-drawer" aria-label="AI Agent" style={{ width: `${drawerWidth}px` }}>
            <div
              className="ai-chat-resize-handle"
              role="separator"
              aria-label="Thay đổi độ rộng AI Agent"
              aria-orientation="vertical"
              aria-valuemin={minDrawerWidth()}
              aria-valuemax={Math.floor(maxDrawerWidth())}
              aria-valuenow={Math.round(drawerWidth)}
              tabIndex={0}
              onPointerDown={startDrawerResize}
              onPointerMove={event => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                  resizeDrawer(window.innerWidth - event.clientX);
                }
              }}
              onKeyDown={event => {
                if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                  event.preventDefault();
                  resizeDrawer(drawerWidth + (event.key === 'ArrowLeft' ? 24 : -24));
                } else if (event.key === 'Home') {
                  resizeDrawer(minDrawerWidth());
                } else if (event.key === 'End') {
                  resizeDrawer(maxDrawerWidth());
                }
              }}
            />
            <AIChatSidebar key={dashboardId} onClose={() => setOpen(false)} />
          </aside>
        </div>,
        document.body,
      )}
    </>
  );
}
/** Attach the AI Agent beside Superset's dashboard actions menu. */
export function installDashboardAI(): () => void {
  let root: HTMLSpanElement | undefined;
  let frame = 0;
  let mountedDashboard = '';

  const clear = () => {
    if (root) {
      ReactDOM.unmountComponentAtNode(root);
      root.remove();
    }
    root = undefined;
    mountedDashboard = '';
  };

  const mount = () => {
    frame = 0;
    const match = window.location.pathname.match(/^\/superset\/dashboard\/([^/]+)/);
    const menu = document.querySelector<HTMLButtonElement>(
      'button[data-test="actions-trigger"], button[aria-label="Menu actions trigger"]',
    );
    if (!match || !menu) {
      if (root) clear();
      return;
    }

    const dashboardId = decodeURIComponent(match[1]);
    const anchor = menu.parentElement?.parentElement?.classList.contains('right-button-panel')
      ? menu.parentElement
      : menu;
    if (root?.isConnected && mountedDashboard === dashboardId && root.nextElementSibling === anchor) {
      return;
    }

    clear();
    root = document.createElement('span');
    root.dataset.aiDashboardAssistant = 'true';
    root.className = 'ai-dashboard-trigger-mount';
    anchor.before(root);
    mountedDashboard = dashboardId;
    ReactDOM.render(<DashboardAI dashboardId={dashboardId} />, root);
  };

  const schedule = () => {
    if (!frame) frame = window.requestAnimationFrame(mount);
  };
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener('popstate', schedule);
  mount();

  return () => {
    observer.disconnect();
    window.removeEventListener('popstate', schedule);
    if (frame) window.cancelAnimationFrame(frame);
    clear();
  };
}
