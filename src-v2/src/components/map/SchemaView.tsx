import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'
import type { GraphNode, TopologyGraph } from '../../lib/gis'
import { STATUS_COLOR, STATUS_LABEL } from '../../lib/gis'

const NODE_W = 200
const NODE_H = 76

type AssetNodeData = { node: GraphNode }

function AssetNode({ data, selected }: NodeProps<Node<AssetNodeData>>) {
  const node = data.node
  const statusColor = STATUS_COLOR[node.status] ?? '#6B7A8A'
  const dim = !node.energized
  return (
    <div
      className={`w-[200px] rounded-xl border bg-surface1 px-3 py-2 text-left transition ${
        selected ? 'ring-2 ring-accent' : ''
      } ${node.grounded ? 'border-ground' : 'border-line'} ${dim ? 'opacity-70' : ''}`}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
      <div className="flex items-center gap-2">
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm"
          style={{ background: `${node.type_color ?? '#4C9AFF'}22` }}
        >
          {node.type_icon ?? '●'}
        </span>
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold text-ink">{node.code}</div>
          <div className="truncate text-[10px] text-ink3">{node.type_name}</div>
        </div>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[10px]">
        <span style={{ color: statusColor }}>●</span>
        <span className="text-ink2">{STATUS_LABEL[node.status] ?? node.status}</span>
        {node.grounded ? <span className="text-ground">⏚</span> : null}
        {node.is_source ? <span className="ml-auto text-warm">источник</span> : null}
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
    </div>
  )
}

const nodeTypes = { asset: AssetNode }

function layout(graph: TopologyGraph): { nodes: Node<AssetNodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 26, ranksep: 64, marginx: 16, marginy: 16 })

  graph.nodes.forEach((node) => g.setNode(node.id, { width: NODE_W, height: NODE_H }))
  graph.edges.forEach((edge) => {
    if (g.hasNode(edge.from_asset_id) && g.hasNode(edge.to_asset_id)) {
      g.setEdge(edge.from_asset_id, edge.to_asset_id)
    }
  })
  dagre.layout(g)

  const nodes: Node<AssetNodeData>[] = graph.nodes.map((node) => {
    const position = g.node(node.id)
    return {
      id: node.id,
      type: 'asset',
      position: { x: (position?.x ?? 0) - NODE_W / 2, y: (position?.y ?? 0) - NODE_H / 2 },
      data: { node },
    }
  })

  const edges: Edge[] = graph.edges.map((edge) => {
    const open = edge.state !== 'connected'
    const jumper = edge.link_type === 'jumper'
    return {
      id: edge.id,
      source: edge.from_asset_id,
      target: edge.to_asset_id,
      label: edge.label,
      // «анимированные» связи React Flow рисует пунктиром, а у нас пунктир
      // означает разомкнутую связь — поэтому анимацию не включаем
      animated: false,
      style: {
        stroke: open ? '#6B7A8A' : jumper ? '#A56BFF' : '#4C9AFF',
        strokeWidth: open ? 1.2 : 1.8,
        strokeDasharray: open ? '6 4' : undefined,
      },
      labelStyle: { fill: '#9FB0C0', fontSize: 10 },
      labelBgStyle: { fill: '#0B1014', fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: open ? '#6B7A8A' : '#4C9AFF' },
    }
  })

  return { nodes, edges }
}

function Flow({
  graph,
  selectedId,
  onSelect,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const { fitView } = useReactFlow()
  const { nodes, edges } = useMemo(() => layout(graph), [graph])

  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 60)
    return () => clearTimeout(timer)
  }, [nodes, fitView])

  return (
    <ReactFlow
      nodes={nodes.map((node) => ({ ...node, selected: node.id === selectedId }))}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.id)}
      fitView
      minZoom={0.15}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
      className="bg-[#070C10]"
    >
      <Background color="#1B2733" gap={24} size={1} />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  )
}

export function SchemaView({
  graph,
  selectedId,
  onSelect,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <ReactFlowProvider>
      <div className="h-full w-full">
        <Flow graph={graph} selectedId={selectedId} onSelect={onSelect} />
      </div>
    </ReactFlowProvider>
  )
}
