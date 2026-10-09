import { installDashboardSemanticLayer } from './integration/installDashboardSemanticLayer';
import './features/semantic-layer/semantic-layer.css';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installDashboardSemanticLayer, { once: true });
} else {
  installDashboardSemanticLayer();
}
