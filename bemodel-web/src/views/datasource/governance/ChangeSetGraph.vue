<template>
  <div ref="rootRef" class="cs-graph">
    <GraphCanvas
      v-if="items.length"
      ref="graphRef"
      :nodes="graphData.nodes"
      :edges="graphData.edges"
      :categories="GRAPH_CATEGORIES"
      layout="force"
      height="560px"
      :loading="loading"
      show-legend
      :tooltip-formatter="tooltipFormatter"
      @node-click="onNodeClick"
    />
    <el-empty v-else-if="!loading" description="当前筛选无匹配建议" />
    <div class="graph-hint">点击概念节点展开 / 收起属性与映射子图；点击其他节点定位到列表行</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import GraphCanvas from '../../../components/GraphCanvas.vue'
import { buildGroups, buildGraphData, GRAPH_CATEGORIES, TYPE_META, REVIEW_META, OPERATION_META } from './hierarchy'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['locate'])

const rootRef = ref(null)
const graphRef = ref(null)
// 下钻状态：已展开属性子图的概念码集合（替换式更新保证触发响应）
const expandedConcepts = ref(new Set())
// 非响应式坐标缓存：跨重算保持节点位置，避免 toggle/筛选时全图跳动
const posCache = new Map()
const viewport = ref({ w: 1200, h: 560 })

onMounted(() => {
  viewport.value = { w: rootRef.value?.clientWidth || 1200, h: 560 }
  // 对话框动画期间容器尺寸可能未定，挂载后兜底 resize 一次
  nextTick(() => graphRef.value?.resize())
})

const model = computed(() => buildGroups(props.items))
const graphData = computed(() =>
  buildGraphData(model.value, expandedConcepts.value, posCache, viewport.value))

const onNodeClick = (node) => {
  if (node._kind === 'concept') {
    const next = new Set(expandedConcepts.value)
    next.has(node._code) ? next.delete(node._code) : next.add(node._code)
    expandedConcepts.value = next
    return
  }
  const item = graphData.value.itemIndex.get(node.id)
  if (item) emit('locate', item)
}

const escapeHtml = (text) => String(text || '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')

const tooltipFormatter = (params) => {
  const item = graphData.value.itemIndex.get(params.data?.id)
  if (!item) return params.data?.name ?? ''
  const operation = OPERATION_META[item.operation]?.label || item.operation
  const review = REVIEW_META[item.reviewStatus]?.label || item.reviewStatus
  const type = TYPE_META[item.itemType]?.label || item.itemType
  const reason = item.reason ? `<br/>${escapeHtml(item.reason.slice(0, 80))}` : ''
  return `<b>${type}</b> ${escapeHtml(item.targetKey)}<br/>${operation} · ${review} · 置信度 ${Math.round((item.confidence || 0) * 100)}%${reason}`
}
</script>

<style scoped>
.cs-graph {
  position: relative;
}

.graph-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary, #909399);
  text-align: center;
}
</style>
