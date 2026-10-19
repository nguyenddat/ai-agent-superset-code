import { installSemanticLayer } from './integration/installSemanticLayer';
import './features/semantic-layer/semantic-layer.css';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installSemanticLayer, { once: true });
} else {
  installSemanticLayer();
}
