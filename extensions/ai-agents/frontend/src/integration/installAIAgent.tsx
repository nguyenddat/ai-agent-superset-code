import React from 'react';
import ReactDOM from 'react-dom';
import { AGENT_PAGE, AgentPage } from '../features/chat/AgentPage';

const HEADER_SELECTOR = 'header#main-menu';
const NAVBAR_SELECTOR = 'ul[data-test="navbar-top"]';
const NAV_ITEM_SELECTOR = '[data-test="ai-agent-nav-item"]';
// Lucide's "sparkles", inlined because the navbar item is plain markup rather than a React root.
const SPARKLES_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063'
  + 'l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5'
  + 'A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135'
  + 'a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/></svg>';

/** Superset's "SQL" menu; the AI Agent item sits right after it, before the Semantic Layer menus. */
function sqlMenuItem(navbar: HTMLUListElement): Element | null {
  return Array.from(navbar.children).find(item => (
    !item.matches(NAV_ITEM_SELECTOR) && item.textContent?.trim().startsWith('SQL')
  )) ?? null;
}

const isAgentPage = () => `${window.location.pathname.replace(/\/$/, '')}/` === AGENT_PAGE;

/** From a dashboard, the navbar item opens a new conversation about that dashboard. */
function agentPageHref(): string {
  const match = window.location.pathname.match(/^\/superset\/dashboard\/([^/]+)/);
  return match ? `${AGENT_PAGE}?dashboard=${match[1]}` : AGENT_PAGE;
}

/**
 * Put AI Agent in Superset's navbar for every signed-in user, between "SQL" and the Semantic Layer menus, and render
 * the AI Agent page below Superset's header at `/ai-agent/`.
 */
export function installAIAgent(): () => void {
  let host: HTMLDivElement | undefined;
  let frame = 0;

  const unmountPage = () => {
    if (!host) return;
    ReactDOM.unmountComponentAtNode(host);
    host.remove();
    host = undefined;
  };

  const sync = () => {
    frame = 0;
    const navbar = document.querySelector<HTMLUListElement>(NAVBAR_SELECTOR);
    if (navbar) {
      let item = navbar.querySelector<HTMLLIElement>(NAV_ITEM_SELECTOR);
      if (!item) {
        item = document.createElement('li');
        item.className = 'ant-menu-item ant-menu-item-only-child ai-nav-item';
        item.setAttribute('role', 'menuitem');
        item.dataset.test = 'ai-agent-nav-item';
        item.innerHTML = '<span class="ant-menu-title-content">'
          + `<a class="ai-nav-link">${SPARKLES_ICON}AI Agent</a></span>`;
      }
      const sqlItem = sqlMenuItem(navbar);
      if (sqlItem && item.previousElementSibling !== sqlItem) sqlItem.after(item);
      else if (!sqlItem && !item.parentElement) navbar.append(item);
      const link = item.querySelector<HTMLAnchorElement>('a.ai-nav-link');
      const href = agentPageHref();
      if (link && link.getAttribute('href') !== href) link.setAttribute('href', href);
      item.classList.toggle('ant-menu-item-selected', isAgentPage());
    }

    if (!isAgentPage()) {
      unmountPage();
      return;
    }
    const header = document.querySelector<HTMLElement>(HEADER_SELECTOR);
    if (host || !header) return;
    host = document.createElement('div');
    host.style.setProperty('--ai-nav-height', `${header.offsetHeight}px`);
    header.after(host);
    ReactDOM.render(<AgentPage />, host);
  };

  const schedule = () => {
    if (!frame) frame = window.requestAnimationFrame(sync);
  };
  const observer = new MutationObserver(schedule);
  let active = true;

  fetch('/api/v1/me/', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(response => {
      if (!active || !response.ok) return;
      observer.observe(document.body, { childList: true, subtree: true });
      window.addEventListener('popstate', schedule);
      sync();
    })
    .catch(() => undefined);

  return () => {
    active = false;
    observer.disconnect();
    window.removeEventListener('popstate', schedule);
    if (frame) window.cancelAnimationFrame(frame);
    document.querySelectorAll(NAV_ITEM_SELECTOR).forEach(item => item.remove());
    unmountPage();
  };
}
