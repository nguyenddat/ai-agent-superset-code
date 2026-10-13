import { installDashboardAI } from './integration/installDashboardAI';
import './features/chat/components/AIChatSidebar.css';
import './styles/shadcn.css';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installDashboardAI, { once: true });
} else {
  installDashboardAI();
}
