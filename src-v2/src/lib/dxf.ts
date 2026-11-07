/** Экспорт однолинейной схемы в DXF (R12) — открывается в nanoCAD/AutoCAD. */

import type { TopologyGraph } from './gis'

export interface DxfPoint {
  x: number
  y: number
}

function pair(code: number, value: string | number): string {
  return `${code}\n${value}\n`
}

function line(from: DxfPoint, to: DxfPoint, layer = 'LINKS'): string {
  return (
    '0\nLINE\n' +
    pair(8, layer) +
    pair(10, from.x.toFixed(2)) +
    pair(20, from.y.toFixed(2)) +
    pair(30, 0) +
    pair(11, to.x.toFixed(2)) +
    pair(21, to.y.toFixed(2)) +
    pair(31, 0)
  )
}

function rect(x: number, y: number, width: number, height: number, layer = 'NODES'): string {
  const corners: DxfPoint[] = [
    { x, y },
    { x: x + width, y },
    { x: x + width, y: y + height },
    { x, y: y + height },
  ]
  return corners
    .map((point, index) => line(point, corners[(index + 1) % corners.length], layer))
    .join('')
}

function text(x: number, y: number, value: string, height = 12, layer = 'LABELS'): string {
  const safe = value.replace(/[\r\n]/g, ' ')
  return (
    '0\nTEXT\n' +
    pair(8, layer) +
    pair(10, x.toFixed(2)) +
    pair(20, y.toFixed(2)) +
    pair(30, 0) +
    pair(40, height) +
    pair(1, safe)
  )
}

function circle(x: number, y: number, radius: number, layer = 'PORTS'): string {
  return (
    '0\nCIRCLE\n' +
    pair(8, layer) +
    pair(10, x.toFixed(2)) +
    pair(20, y.toFixed(2)) +
    pair(30, 0) +
    pair(40, radius.toFixed(2))
  )
}

export interface DxfNode {
  id: string
  code: string
  name: string
  x: number
  y: number
  width: number
  height: number
  ports: Array<{ id: string; code: string; fx: number; fy: number }>
}

export interface DxfEdge {
  from: { x: number; y: number }
  to: { x: number; y: number }
  label: string
}

/**
 * Собрать DXF: узлы — прямоугольники с подписями, порты — окружности,
 * связи — линии. Ось Y инвертируется, чтобы схема не была «вверх ногами».
 */
export function buildDxf(nodes: DxfNode[], edges: DxfEdge[]): string {
  if (nodes.length === 0) {
    return '0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n'
  }

  const maxY = Math.max(...nodes.map((node) => node.y + node.height)) + 40
  const flip = (point: { x: number; y: number }) => ({ x: point.x, y: maxY - point.y })

  let entities = ''

  for (const node of nodes) {
    const topLeft = flip({ x: node.x, y: node.y + node.height })
    entities += rect(topLeft.x, topLeft.y, node.width, node.height)
    entities += text(topLeft.x + 8, topLeft.y + node.height - 18, node.code, 14)
    entities += text(topLeft.x + 8, topLeft.y + node.height - 34, node.name.slice(0, 40), 9)
  }

  for (const node of nodes) {
    for (const port of node.ports) {
      const point = flip({
        x: node.x + port.fx * node.width,
        y: node.y + port.fy * node.height,
      })
      entities += circle(point.x, point.y, 4)
    }
  }

  for (const edge of edges) {
    const from = flip(edge.from)
    const to = flip(edge.to)
    entities += line(from, to)
    if (edge.label) {
      entities += text((from.x + to.x) / 2, (from.y + to.y) / 2 + 4, edge.label, 8, 'LABELS')
    }
  }

  return (
    '0\nSECTION\n' +
    '2\nHEADER\n' +
    '9\n$ACADVER\n1\nAC1009\n' +
    '0\nENDSEC\n' +
    '0\nSECTION\n' +
    '2\nENTITIES\n' +
    entities +
    '0\nENDSEC\n' +
    '0\nEOF\n'
  )
}

export function downloadDxf(graph: TopologyGraph, positions: Record<string, { x: number; y: number }>, portPositions: Record<string, { x: number; y: number }>, width = 210, height = 84) {
  const nodes: DxfNode[] = graph.nodes.map((node) => ({
    id: node.id,
    code: node.code,
    name: node.name,
    x: positions[node.id]?.x ?? 0,
    y: positions[node.id]?.y ?? 0,
    width,
    height,
    ports: node.ports.map((port) => {
      const point = portPositions[port.id]
      return { id: port.id, code: port.code, fx: point?.x ?? 0, fy: point?.y ?? 0.5 }
    }),
  }))

  const edges: DxfEdge[] = graph.edges.map((edge) => ({
    from: positions[edge.from_asset_id] ?? { x: 0, y: 0 },
    to: positions[edge.to_asset_id] ?? { x: 0, y: 0 },
    label: edge.label,
  }))

  const content = buildDxf(nodes, edges)
  const blob = new Blob([content], { type: 'application/dxf' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'karier-schema.dxf'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
