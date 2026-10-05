import { installDashboardAI } from './integration/installDashboardAI';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installDashboardAI, { once: true });
} else {
  installDashboardAI();
}
