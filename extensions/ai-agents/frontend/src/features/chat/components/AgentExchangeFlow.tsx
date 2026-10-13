import {
  BaseEdge,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  Handle,
  Position,
  ReactFlow,
  getBezierPath,
} from '@xyflow/react';
import { Bot, Check, LoaderCircle, Wrench } from 'lucide-react';
import '@xyflow/react/dist/style.css';

type AgentNodeData = { agent: string; label: string; active: boolean; complete: boolean };
type AgentEdgeData = { active: boolean };
type AgentNode = Node<AgentNodeData>;
type AgentEdge = Edge<AgentEdgeData>;
type ToolUse = { name: string; active: boolean };

const labels: Record<string, string> = {
  bi_planner: 'BI Planner',
  metadata_resolution: 'Metadata Resolution',
  data_builder: 'Data Builder',
};

function agentName(agent: string) {
  return labels[agent] || agent.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
}

function AgentBotNode({ data }: NodeProps<AgentNode>) {
  return (
    <div className={`ai-agent-flow-node is-${data.agent}${data.active ? ' is-active' : ''}`}>
      <Handle type="target" position={Position.Left} className="ai-agent-flow-handle" />
      <span className="ai-agent-flow-avatar" aria-hidden="true"><Bot /></span>
      <span className="ai-agent-flow-node-copy">
        <strong>{data.label}</strong>
        <small>{data.active ? 'Đang suy nghĩ' : data.complete ? 'Đã phản hồi' : 'Đang chờ'}</small>
      </span>
      {data.active ? <LoaderCircle className="ai-agent-flow-state is-loading" aria-label="Đang suy nghĩ" /> : data.complete ? <Check className="ai-agent-flow-state" aria-label="Đã phản hồi" /> : null}
      <Handle type="source" position={Position.Right} className="ai-agent-flow-handle" />
    </div>
  );
}

function AnimatedSvgEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<AgentEdge>) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const pathId = `agent-edge-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  return (
    <>
      <BaseEdge id={pathId} path={edgePath} className={`ai-agent-flow-edge${data?.active ? ' is-active' : ''}`} />
      {data?.active ? (
        <circle r="3.5" className="ai-agent-flow-particle" aria-hidden="true">
          <animateMotion dur="1.1s" repeatCount="indefinite" keyPoints="0;1" keyTimes="0;1" calcMode="linear">
            <mpath href={`#${pathId}`} />
          </animateMotion>
        </circle>
      ) : null}
    </>
  );
}

const nodeTypes = { agentBot: AgentBotNode };
const edgeTypes = { animatedSvg: AnimatedSvgEdge };

function ToolList({ tools }: { tools: ToolUse[] }) {
  if (!tools.length) return null;
  return (
    <ul className="ai-agent-bubble-tools" aria-label="Công cụ agent đang sử dụng">
      {tools.map((tool, index) => (
        <li key={`${tool.name}-${index}`} className={tool.active ? 'is-active' : ''}>
          {tool.active ? <LoaderCircle aria-hidden="true" /> : <Wrench aria-hidden="true" />}
          <span>{tool.name}</span>
        </li>
      ))}
    </ul>
  );
}

function AgentBubble({ agent, message, active, tools }: { agent: string; message: string; active: boolean; tools: ToolUse[] }) {
  return (
    <div className={`ai-agent-speech-bubble${active ? ' is-thinking' : ''}`}>
      <div className="ai-agent-speech-heading">
        <strong>{agentName(agent)}</strong>
        {active ? <span className="ai-agent-thinking-label"><LoaderCircle aria-hidden="true" /> Đang suy nghĩ</span> : <Check aria-label="Đã chốt" />}
      </div>
      {message ? <p>{message}</p> : active ? <p className="ai-agent-thinking-dots" aria-label="Đang suy nghĩ"><i /><i /><i /></p> : null}
      <ToolList tools={tools} />
    </div>
  );
}

export function AgentExchangeFlow({ from, to, message, active, senderTools = [], recipientTools = [], showRecipientThinking = false, showSenderThinking = false }: {
  from: string;
  to: string;
  message: string;
  active: boolean;
  senderTools?: ToolUse[];
  recipientTools?: ToolUse[];
  showRecipientThinking?: boolean;
  showSenderThinking?: boolean;
}) {
  const nodes: AgentNode[] = [
    { id: 'sender', type: 'agentBot', position: { x: 0, y: 6 }, data: { agent: from, label: agentName(from), active: showSenderThinking, complete: !showSenderThinking }, draggable: false, selectable: false },
    { id: 'recipient', type: 'agentBot', position: { x: 214, y: 6 }, data: { agent: to, label: agentName(to), active: showRecipientThinking, complete: !showRecipientThinking }, draggable: false, selectable: false },
  ];
  const edges: AgentEdge[] = [{
    id: 'agent-handoff', source: 'sender', target: 'recipient', type: 'animatedSvg',
    data: { active: showRecipientThinking || showSenderThinking }, selectable: false, animated: false,
  }];

  return (
    <article className={`ai-agent-exchange-flow${active ? ' is-active' : ''}`} aria-label={`${agentName(from)} trao đổi với ${agentName(to)}`}>
      <div className="ai-agent-flow-canvas" aria-hidden="true">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={false}
          zoomOnScroll={false} zoomOnDoubleClick={false} zoomOnPinch={false} minZoom={1} maxZoom={1}
          fitView fitViewOptions={{ padding: 0.02 }} proOptions={{ hideAttribution: true }} />
      </div>
      <div className="ai-agent-exchange-bubbles">
        <AgentBubble agent={from} message={showSenderThinking ? '' : message} active={showSenderThinking} tools={senderTools} />
        {showRecipientThinking ? <AgentBubble agent={to} message="" active tools={recipientTools} /> : null}
      </div>
    </article>
  );
}
