import { installAIAgent } from './integration/installAIAgent';
import './features/chat/AgentPage.css';
import './features/schema-link/SchemaLink.css';
import './styles/shadcn.css';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installAIAgent, { once: true });
} else {
  installAIAgent();
}
