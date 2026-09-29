// AI 本体治理变更集：列表项 → 概念分组 / 层次树 / 关系图 的纯函数构建模块。
// 图表色沿用 EP 调色板硬编码（与 ontology/architecture 图表一致）；页面样式走 tokens.css。

export const TYPE_META = {
  CONCEPT: { label: '概念', color: '#409eff', tag: 'primary' },
  ATTRIBUTE: { label: '属性', color: '#67c23a', tag: 'success' },
  MAPPING: { label: '映射', color: '#13c2c2', tag: 'info' },
  TERM: { label: '术语', color: '#722ed1', tag: 'primary' },
  RELATION: { label: '关系', color: '#e6a23c', tag: 'warning' },
  RULE: { label: '规则', color: '#e6a23c', tag: 'warning' },
  ACTION: { label: '动作', color: '#e6a23c', tag: 'warning' },
  METRIC: { label: '指标', color: '#e6a23c', tag: 'warning' }
}

export const REVIEW_META = {
  ACCEPTED: { label: '已接受', tag: 'success' },
  REJECTED: { label: '已拒绝', tag: 'danger' },
  NEEDS_INPUT: { label: '待补充', tag: 'warning' },
  PENDING: { label: '待审核', tag: 'info' }
}

export const OPERATION_META = {
  REUSE_EXISTING: { label: '复用已有', tag: 'info' },
  CREATE: { label: '新建', tag: 'primary' },
  EXTEND: { label: '扩展', tag: 'success' },
  CONFLICT: { label: '冲突', tag: 'danger' },
  INSUFFICIENT_EVIDENCE: { label: '证据不足', tag: 'warning' }
}

export const GRAPH_CATEGORIES = [
  { name: '新建概念', itemStyle: { color: '#409eff' } },
  { name: '已有概念', itemStyle: { color: '#909399' } },
  { name: '属性', itemStyle: { color: '#67c23a' } },
  { name: '映射', itemStyle: { color: '#13c2c2' } },
  { name: '术语', itemStyle: { color: '#722ed1' } },
  { name: '规范元素', itemStyle: { color: '#e6a23c' } },
  { name: '游离', itemStyle: { color: '#f56c6c' } }
]

// dependencies 元素格式为 "TYPE:targetKey"，从中还原概念码（兜底路径）
function conceptFromDependencies(item) {
  for (const dep of item.dependencies || []) {
    const separator = String(dep || '').indexOf(':')
    if (separator <= 0) continue
    const kind = dep.slice(0, separator)
    const key = dep.slice(separator + 1)
    if (kind === 'CONCEPT') return key
    if (kind === 'ATTRIBUTE' && key.includes('.')) return key.split('.')[0]
  }
  return null
}

function conceptCodeOf(item) {
  switch (item.itemType) {
    case 'CONCEPT':
      return item.targetKey || item.payload?.code || null
    case 'ATTRIBUTE':
      if ((item.targetKey || '').includes('.')) return item.targetKey.split('.')[0]
      return item.payload?.conceptCode || conceptFromDependencies(item)
    case 'RELATION':
      return null
    default:
      return item.payload?.conceptCode || conceptFromDependencies(item)
  }
}

export function attrCodeOf(item) {
  if (item.itemType === 'ATTRIBUTE') {
    if ((item.targetKey || '').includes('.')) return item.targetKey.split('.').pop()
    return item.payload?.attrCode || item.targetKey
  }
  return item.payload?.attrCode || null
}

export function shortLabel(item) {
  switch (item.itemType) {
    case 'ATTRIBUTE':
      return attrCodeOf(item) || item.targetKey
    case 'MAPPING': {
      const table = item.payload?.tableName || item.sourceTable || ''
      const column = item.payload?.columnName || item.sourceColumn || ''
      return table && column ? `${table}.${column}` : item.targetKey
    }
    case 'RELATION':
      return item.payload?.relationName
        ? `${item.payload.relationName} → ${item.payload.toConcept || '?'}`
        : item.targetKey
    default:
      return item.targetKey
  }
}

// 分组：概念 → { 属性 → 映射 }，术语/规则/动作/指标挂概念层，关系单列，无法归组的进 orphans。
// 概念可能不在变更集内（匹配已发布概念时无 CONCEPT 项），此时建 virtual 组。
export function buildGroups(items) {
  const groups = new Map()
  const relations = []
  const orphans = []

  const ensureGroup = (code, name) => {
    if (!code) return null
    if (!groups.has(code)) {
      groups.set(code, {
        conceptCode: code, conceptName: name || code, virtual: true, conceptItem: null,
        attrs: new Map(), directMappings: [], conceptLevel: []
      })
    } else if (name && groups.get(code).virtual && groups.get(code).conceptName === code) {
      groups.get(code).conceptName = name
    }
    return groups.get(code)
  }

  // 第一遍：真实 CONCEPT 项建组（保证 virtual 标记不被虚拟组抢占）
  for (const item of items) {
    if (item.itemType !== 'CONCEPT') continue
    const group = ensureGroup(item.targetKey || item.payload?.code)
    group.conceptItem = item
    group.virtual = false
    group.conceptName = item.payload?.name || item.targetKey
  }
  // 第二遍：ATTRIBUTE 先入组，保证 MAPPING 归挂不依赖输入顺序
  for (const item of items) {
    if (item.itemType !== 'ATTRIBUTE') continue
    const code = conceptCodeOf(item)
    if (!code) { orphans.push(item); continue }
    ensureGroup(code).attrs.set(attrCodeOf(item) || `__${item.id}`, { item, mappings: [] })
  }
  // 第三遍：其余类型
  for (const item of items) {
    if (item.itemType === 'CONCEPT' || item.itemType === 'ATTRIBUTE') continue
    if (item.itemType === 'RELATION') {
      relations.push(item)
      ensureGroup(item.payload?.fromConcept, item.payload?.fromConceptName)
      ensureGroup(item.payload?.toConcept, item.payload?.toConceptName)
      continue
    }
    const code = conceptCodeOf(item)
    if (!code) { orphans.push(item); continue }
    const group = ensureGroup(code)
    if (item.itemType === 'MAPPING') {
      const entry = item.payload?.attrCode && group.attrs.get(item.payload.attrCode)
      if (entry) entry.mappings.push(item)
      else group.directMappings.push(item)
    } else {
      group.conceptLevel.push(item)
    }
  }
  return { groups, relations, orphans }
}

const byConfidenceDesc = (a, b) => (b.confidence || 0) - (a.confidence || 0)

// 层次树：概念根 → 属性 → 孙级映射；术语/规则/动作/指标/关系挂概念层；孤儿单独分组。
export function buildTreeData(model) {
  const treeOrphans = [...model.orphans]
  const relationChildren = new Map()
  for (const relation of model.relations) {
    const from = relation.payload?.fromConcept
    if (from && model.groups.has(from)) {
      if (!relationChildren.has(from)) relationChildren.set(from, [])
      relationChildren.get(from).push(relation)
    } else {
      treeOrphans.push(relation)
    }
  }

  const leafNode = (item) => ({ key: `${item.itemType}:${item.id}`, label: shortLabel(item), item })
  const tree = []
  for (const group of model.groups.values()) {
    const children = []
    const attrNodes = [...group.attrs.values()].sort(byConfidenceDesc).map((entry) => ({
      ...leafNode(entry.item),
      children: [...entry.mappings].sort(byConfidenceDesc).map(leafNode)
    }))
    children.push(...attrNodes)
    children.push(...[...group.directMappings].sort(byConfidenceDesc).map(leafNode))
    children.push(...[...group.conceptLevel].sort(byConfidenceDesc).map(leafNode))
    children.push(...[...(relationChildren.get(group.conceptCode) || [])].sort(byConfidenceDesc).map(leafNode))
    tree.push({
      key: group.conceptItem ? `CONCEPT:${group.conceptItem.id}` : `CONCEPT-VIRTUAL:${group.conceptCode}`,
      label: group.conceptName,
      item: group.conceptItem || null,
      virtual: group.virtual,
      attrCount: group.attrs.size + group.directMappings.length,
      children
    })
  }
  tree.sort((a, b) => b.attrCount - a.attrCount || a.label.localeCompare(b.label))
  if (treeOrphans.length) {
    tree.push({
      key: '__orphan__', label: `游离建议（${treeOrphans.length}）`, item: null, orphan: true,
      attrCount: treeOrphans.length, children: treeOrphans.sort(byConfidenceDesc).map(leafNode)
    })
  }
  return tree
}

// 关系图：概念为中心可下钻。expanded 为已展开概念码集合；posCache 跨重算保持节点坐标，
// 避免 toggle/筛选重算时全图跳动。节点只放标量字段（GraphCanvas 对 nodes 做 deep watch），
// 原始 item 通过返回的 itemIndex 回查。
export function buildGraphData(model, expanded, posCache, viewport) {
  const nodes = []
  const edges = []
  const itemIndex = new Map()
  const width = viewport?.w || 1200
  const height = viewport?.h || 560
  const cx = width / 2
  const cy = height / 2
  const radius = Math.max(140, Math.min(width, height) / 2 - 90)

  const codes = [...model.groups.keys()]
  codes.forEach((code, index) => {
    const group = model.groups.get(code)
    const id = `C:${code}`
    if (!posCache.has(id)) {
      const angle = (2 * Math.PI * index) / Math.max(codes.length, 1)
      posCache.set(id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
    }
    const pos = posCache.get(id)
    const attrCount = group.attrs.size + group.directMappings.length
    nodes.push({
      id, name: group.conceptName, x: pos.x, y: pos.y,
      category: group.virtual ? '已有概念' : '新建概念',
      symbolSize: 30 + Math.min(attrCount, 10) * 2,
      label: {
        show: true,
        formatter: expanded.has(code)
          ? `${group.conceptName}\n▾`
          : attrCount
            ? `${group.conceptName}\n${attrCount} 属性 ▸`
            : group.conceptName
      },
      _kind: 'concept', _code: code
    })
  })

  for (const relation of model.relations) {
    const from = relation.payload?.fromConcept
    const to = relation.payload?.toConcept
    if (!from || !to || !model.groups.has(from) || !model.groups.has(to)) continue
    edges.push({
      source: `C:${from}`, target: `C:${to}`,
      label: { show: true, formatter: relation.payload?.relationName || '', fontSize: 11, color: '#909399' },
      lineStyle: { color: '#95d475', width: 1.5, curveness: 0.12 }
    })
  }

  const markOperationStyle = (item, node) => {
    if (item.operation === 'CONFLICT') {
      node.itemStyle = { borderColor: '#f56c6c', borderWidth: 2, borderType: 'dashed' }
    } else if (item.operation === 'INSUFFICIENT_EVIDENCE') {
      node.itemStyle = { borderColor: '#e6a23c', borderWidth: 2, borderType: 'dashed' }
    }
  }
  const pushLeaf = (id, item, name, category, size, fontSize) => {
    const node = {
      id, name, x: posCache.get(id).x, y: posCache.get(id).y,
      category, symbolSize: size, label: { fontSize }, _kind: 'leaf'
    }
    markOperationStyle(item, node)
    nodes.push(node)
    itemIndex.set(id, item)
  }

  for (const code of expanded) {
    const group = model.groups.get(code)
    const center = posCache.get(`C:${code}`)
    if (!group || !center) continue
    const baseAngle = Math.atan2(center.y - cy, center.x - cx)
    const spread = (distance, index, count) => {
      const span = Math.PI / 2
      const step = count > 1 ? span / (count - 1) : 0
      const angle = baseAngle + (index - (count - 1) / 2) * step
      return { x: center.x + distance * Math.cos(angle), y: center.y + distance * Math.sin(angle) }
    }

    const attrEntries = [...group.attrs.values()]
    const mappingSlots = attrEntries.length + group.directMappings.length
    attrEntries.forEach((entry, i) => {
      const attrId = `A:${entry.item.id}`
      if (!posCache.has(attrId)) posCache.set(attrId, spread(95, i, mappingSlots))
      pushLeaf(attrId, entry.item, attrCodeOf(entry.item) || entry.item.targetKey, '属性', 14, 11)
      edges.push({
        source: `C:${code}`, target: attrId,
        lineStyle: { color: '#c0c4cc', type: 'dashed', width: 1 }, symbol: ['none', 'none']
      })
      entry.mappings.forEach((mapping, j) => {
        const mapId = `M:${mapping.id}`
        if (!posCache.has(mapId)) {
          const anchor = posCache.get(attrId)
          const angle = baseAngle + (j - (entry.mappings.length - 1) / 2) * 0.35
          posCache.set(mapId, { x: anchor.x + 70 * Math.cos(angle), y: anchor.y + 70 * Math.sin(angle) })
        }
        pushLeaf(mapId, mapping, shortLabel(mapping), '映射', 12, 10)
        edges.push({ source: attrId, target: mapId, lineStyle: { color: '#13c2c2', width: 1 } })
      })
    })
    group.directMappings.forEach((mapping, i) => {
      const mapId = `M:${mapping.id}`
      if (!posCache.has(mapId)) posCache.set(mapId, spread(95, attrEntries.length + i, mappingSlots))
      pushLeaf(mapId, mapping, shortLabel(mapping), '映射', 12, 10)
      edges.push({ source: `C:${code}`, target: mapId, lineStyle: { color: '#13c2c2', width: 1 } })
    })
    group.conceptLevel.forEach((item, i) => {
      const nodeId = `${item.itemType}:${item.id}`
      if (!posCache.has(nodeId)) posCache.set(nodeId, spread(75, i, group.conceptLevel.length))
      pushLeaf(nodeId, item, `${TYPE_META[item.itemType]?.label || item.itemType}:${shortLabel(item)}`,
        item.itemType === 'TERM' ? '术语' : '规范元素', 10, 10)
      edges.push({
        source: `C:${code}`, target: nodeId,
        lineStyle: { color: '#c0c4cc', type: 'dashed', width: 1 }, symbol: ['none', 'none']
      })
    })
  }

  if (model.orphans.length) {
    nodes.push({
      id: '__orphan__', name: `游离建议（${model.orphans.length}）`, x: cx, y: cy,
      category: '游离', symbolSize: 20 + Math.min(model.orphans.length, 10), _kind: 'orphan'
    })
  }
  return { nodes, edges, itemIndex }
}
